"""Published workload references never become arbitrary-prompt carbon factors."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from carbontrace.preflight import PreflightRequest, WorkloadReference, build_preflight
from carbontrace.research import COMMIT, records


@pytest.mark.parametrize("workload", sorted({row.workload for row in records()}))
def test_preflight_reference_matches_exact_model_and_workload(
    client: TestClient, workload: str
) -> None:
    """Six supported workloads retain source values, attribution, and missing data."""
    response = client.post(
        "/api/preflight",
        json={
            "prompt": "Write tests for my private example",
            "research_reference": {"workload": workload},
        },
    )
    assert response.status_code == 200
    result = response.json()
    reference = result["research_reference"]
    compact, strong = reference["models"]
    record = next(
        r
        for r in records()
        if r.model_name == "Gemini 3.5 Flash-Lite" and r.workload == workload
    )
    assert Decimal(compact["total_energy_wh"]) == record.energy_wh_mean
    assert Decimal(compact["operational_carbon_g"]) == record.energy_wh_mean * Decimal(
        "0.4"
    )
    assert compact["evidence"]["energy_wh_sd"] == str(record.energy_wh_sd)
    strong_record = next(
        r
        for r in records()
        if r.model_name == "Gemini 3.7 Flash" and r.workload == workload
    )
    assert strong["model_name"] == "Gemini 3.7 Flash"
    assert strong["available"] is True
    assert Decimal(strong["total_energy_wh"]) == strong_record.energy_wh_mean
    assert Decimal(
        strong["operational_carbon_g"]
    ) == strong_record.energy_wh_mean * Decimal("0.4")
    assert result["models"][1]["quality"]["pilot_samples"] == 3
    assert reference["source"]["commit"] == COMMIT
    assert reference["source"]["license"] == "CC BY-NC 4.0"
    assert reference["request"]["sessions"] == 1
    assert result["carbon"]["carbon_g"] is None
    assert result["carbon_scenario"] is None
    assert result["live_model_calls"] == reference["live_model_calls"] == 0
    assert "private example" not in response.text
    assert client.get("/api/history").json() == []


def test_reference_is_explicit_and_independent_of_prompt_tokens_and_selection() -> None:
    """Reference energy is unchanged when the user's request or selection changes."""
    plain = build_preflight(PreflightRequest(prompt="Write tests"))
    assert plain.research_reference is None
    settings = WorkloadReference(workload="chat.light")
    short = build_preflight(
        PreflightRequest(prompt="Write tests", research_reference=settings)
    )
    long = build_preflight(
        PreflightRequest(
            prompt="Write tests " * 100,
            context="Extra code context",
            generated_low=1024,
            generated_high=4096,
            selected_model="compact",
            research_reference=settings,
        )
    )
    assert short.research_reference == long.research_reference
    assert short.models[0].cost_usd != long.models[0].cost_usd
    assert plain.models[0].cost_usd == short.models[0].cost_usd
    assert plain.models[0].quality == short.models[0].quality


def test_reference_grid_changes_only_operational_carbon() -> None:
    """Zero grid preserves facility energy for both models; no extra PUE."""
    default = build_preflight(
        PreflightRequest(
            prompt="Tests", research_reference=WorkloadReference(workload="chat.light")
        )
    ).research_reference
    zero = build_preflight(
        PreflightRequest(
            prompt="Tests",
            research_reference=WorkloadReference(
                workload="chat.light", grid_g_per_kwh=Decimal(0)
            ),
        )
    ).research_reference
    assert default is not None and zero is not None
    assert (
        default.models[0].total_energy_wh
        == zero.models[0].total_energy_wh
        == Decimal("0.062106712990")
    )
    assert default.models[0].operational_carbon_g == Decimal("0.024842685196")
    assert zero.models[0].operational_carbon_g == 0
    assert zero.models[1].operational_carbon_g == 0
    assert zero.models[1].total_energy_wh == default.models[1].total_energy_wh
    assert zero.models[1].total_energy_wh == Decimal("0.141987097860")


@pytest.mark.parametrize(
    "reference",
    [
        {},
        {"workload": "auto"},
        {"workload": "chat.light", "sessions": 5},
        {"workload": "chat.light", "grid_g_per_kwh": -1},
        {"workload": "chat.light", "grid_g_per_kwh": 2001},
        {"workload": "chat.light", "model_b": "Gemini 3.7 Flash"},
        {"workload": "chat.light", "provenance": "measured"},
    ],
)
def test_reference_rejects_unsupported_or_misleading_overrides(
    client: TestClient, reference: dict[str, object]
) -> None:
    """A preview cannot silently substitute a sibling, scale sessions, or claim measurement."""
    assert (
        client.post(
            "/api/preflight",
            json={"prompt": "Write tests", "research_reference": reference},
        ).status_code
        == 422
    )
