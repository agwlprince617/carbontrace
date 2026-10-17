"""Illustrative pre-send carbon stays distinct from measured provider evidence."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from carbontrace.benchmark import prompt
from carbontrace.benchmarks import EXERCISES
from carbontrace.preflight import PreflightRequest, PreflightScenario, build_preflight


def test_assumed_carbon_calculation_and_export_provenance(client: TestClient) -> None:
    """Hand-calculated seconds, Wh, and gCO2e use consistent dimensional units."""
    response = client.post(
        "/api/preflight",
        json={"prompt": prompt(EXERCISES["clamp"]), "carbon_scenario": {}},
    )
    assert response.status_code == 200
    result = response.json()
    compact, strong = result["models"]
    impact = compact["illustrative_impact"]
    assert impact["assumed_seconds"] == pytest.approx({"low": 5.282, "high": 20.642})
    assert impact["impact"]["energy_wh"] == pytest.approx(
        {"low": 0.05282, "high": 0.41284}
    )
    assert impact["impact"]["carbon_g"] == pytest.approx(
        {"low": 0.021128, "high": 0.165136}
    )
    assert strong["illustrative_impact"]["impact"]["carbon_g"] == pytest.approx(
        {"low": 0.084512, "high": 0.495408}
    )
    assert impact["impact"]["provenance"] == "illustrative_scenario"
    assert result["carbon_scenario"]["provenance"] == "illustrative_assumptions"
    assert "not measured" in result["carbon_scenario_note"]
    assert result["carbon"]["carbon_g"] is None
    assert result["carbon"]["status"] == "insufficient_evidence"
    assert result["live_model_calls"] == 0
    assert client.get("/api/history").json() == []


def test_scenario_is_optional_and_does_not_modify_quality_or_prices() -> None:
    """No numeric estimate without opting in; real evidence is unaffected."""
    draft = prompt(EXERCISES["clamp"])
    plain = build_preflight(PreflightRequest(prompt=draft))
    illustrative = build_preflight(
        PreflightRequest(prompt=draft, carbon_scenario=PreflightScenario())
    )
    assert plain.carbon_scenario is None
    for before, after in zip(plain.models, illustrative.models, strict=True):
        assert before.illustrative_impact is None
        assert before.cost_usd == after.cost_usd
        assert before.quality == after.quality
    assert plain.carbon == illustrative.carbon


def test_model_names_do_not_determine_carbon_and_zero_grid_keeps_energy() -> None:
    """Equal physical assumptions produce equal impacts; zero grid is not zero Wh."""
    draft = "Write tests for a new function with no saved observations"
    assumptions = PreflightScenario.model_validate(
        {"compact_power_w": {"low": 120, "high": 180}}
    )
    result = build_preflight(
        PreflightRequest(prompt=draft, carbon_scenario=assumptions)
    )
    assert result.models[0].illustrative_impact == result.models[1].illustrative_impact
    zero = build_preflight(
        PreflightRequest(
            prompt=draft,
            carbon_scenario=PreflightScenario(grid_g_per_kwh=0),
        )
    )
    for row in zero.models:
        assert row.illustrative_impact is not None
        assert row.illustrative_impact.impact.carbon_g.high == 0
        assert row.illustrative_impact.impact.energy_wh.low > 0


@pytest.mark.parametrize(
    "assumptions",
    [
        {"compact_power_w": {"low": -1, "high": 60}},
        {"strong_power_w": {"low": 200, "high": 100}},
        {"strong_power_w": {"low": 120, "high": 100001}},
        {"input_tokens_per_second": 0},
        {"generated_tokens_per_second": 1000001},
        {"pue": 0.9},
        {"grid_g_per_kwh": -1},
        {"grid_g_per_kwh": 2001},
        {"provenance": "measured"},
        {"real_gemini_energy": 0.24},
    ],
)
def test_invalid_or_false_provenance_assumptions_are_rejected(
    client: TestClient, assumptions: dict[str, object]
) -> None:
    """Inputs cannot manufacture a measured label or break dimensional arithmetic."""
    assert (
        client.post(
            "/api/preflight",
            json={"prompt": "Write tests", "carbon_scenario": assumptions},
        ).status_code
        == 422
    )


def test_site_explains_assumptions_without_project_reference(
    client: TestClient,
) -> None:
    """The requested site content states both the provisional and future method."""
    html = client.get("/").text
    assert "ecolog" not in html.lower()
    assert "What would make this estimate defensible?" in html
    assert "Illustrative scenario · not measured" in html
    assert "For now, the displayed numbers use assumptions." in html


def test_custom_code_and_context_support_editable_scenarios(client: TestClient) -> None:
    """An unseen request can be planned without executing it or claiming quality."""
    draft = "Write tests for:\ndef add(a, b):\n    return a + b"
    response = client.post(
        "/api/preflight",
        json={
            "prompt": draft,
            "context": "Use pytest; include negative integers and café labels.",
            "generated_low": 100,
            "generated_high": 300,
            "carbon_scenario": {
                "compact_power_w": {"low": 25, "high": 50},
                "strong_power_w": {"low": 0, "high": 0},
                "pue": 1.5,
                "grid_g_per_kwh": 500,
                "input_tokens_per_second": 800,
                "generated_tokens_per_second": 40,
            },
        },
    )
    assert response.status_code == 200
    result = response.json()
    compact, strong = result["models"]
    assert compact["input_tokens"]["basis"] == "utf8_planning_heuristic"
    assert all(
        row["quality"]["matched_observation"] is None for row in result["models"]
    )
    assert compact["illustrative_impact"]["impact"]["carbon_g"]["low"] > 0
    assert strong["illustrative_impact"]["impact"]["energy_wh"]["high"] == 0
    assert result["carbon_scenario"]["generated_tokens_per_second"] == 40
    assert result["carbon"]["carbon_g"] is None
    assert result["live_model_calls"] == 0
    assert draft not in response.text
    assert client.get("/api/history").json() == []
