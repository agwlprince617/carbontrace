"""Offline planning arithmetic and truthful evidence boundaries."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from carbontrace.benchmark import prompt
from carbontrace.benchmarks import EXERCISES
from carbontrace.preflight import PreflightRequest, build_preflight, catalog


def test_identical_prompt_uses_observed_count_and_explicit_cost_scenarios() -> None:
    """Past tokenization is reusable evidence; future output remains an assumption."""
    draft = prompt(EXERCISES["clamp"])
    result = build_preflight(PreflightRequest(prompt=draft))
    compact, strong = result.models
    assert compact.input_tokens.low == compact.input_tokens.high == 162
    assert compact.input_tokens.basis == "observed_identical_pilot_prompt"
    assert compact.cost_usd.low == Decimal("0.0006886")
    assert compact.cost_usd.high == Decimal("0.0026086")
    assert strong.model_id == "gemini-3.7-flash"
    assert strong.input_tokens.basis == "observed_identical_pilot_prompt"
    assert (strong.input_tokens.low, strong.input_tokens.high) == (162, 162)
    assert strong.cost_usd.low == Decimal("0.0010815")
    assert strong.cost_usd.high == Decimal("0.0039615")
    assert strong.quality.matched_observation is not None
    assert strong.quality.matched_observation.tests == 6
    assert strong.quality.pilot_samples == 3
    match = compact.quality.matched_observation
    assert match is not None and match.accepted and match.tests == 8
    assert match.detected == match.total_mutations == 4
    assert "new suite" in result.guidance
    assert "Both saved suites met" in result.guidance
    assert result.live_model_calls == 0
    assert result.carbon.energy_wh is None and result.carbon.carbon_g is None
    assert result.carbon.status == "insufficient_evidence"


def test_context_and_prompt_changes_remove_exact_quality_claims() -> None:
    """Related examples cannot become quality predictions for unseen drafts."""
    original = prompt(EXERCISES["clamp"])
    for draft in (
        PreflightRequest(prompt=original + "\nPlease be concise."),
        PreflightRequest(
            prompt=original, context="A private dependency: SECRET-CONTEXT"
        ),
    ):
        result = build_preflight(draft)
        assert all(
            row.quality.scope == "no_matching_pilot_prompt"
            and row.quality.matched_observation is None
            and row.input_tokens.basis == "utf8_planning_heuristic"
            for row in result.models
        )
        assert "no matching quality" in result.guidance
        assert result.prompt_sha256 != hashlib.sha256(original.encode()).hexdigest()
        assert "SECRET-CONTEXT" not in result.model_dump_json()


def test_unicode_payload_and_selection_do_not_fabricate_measurements() -> None:
    """The heuristic includes UTF-8 context and cannot turn price into carbon."""
    request = PreflightRequest(
        prompt="Generate tests for café ☀", context="你好", selected_model="compact"
    )
    result = build_preflight(request)
    assert result.visible_utf8_bytes == len(request.visible_payload().encode())
    assert "Additional context:" in request.visible_payload()
    assert [row.role for row in result.models if row.selected] == ["compact"]
    assert [row.quality.pilot_samples for row in result.models] == [3, 3]
    assert "outside this range" in result.models[0].input_tokens.note
    assert result.carbon.carbon_g is None


def test_example_endpoints_exclude_holdout_and_plans_are_not_saved(
    client: TestClient,
) -> None:
    """Preview arbitrary text as data without persistence, execution, or live unlock."""
    examples = client.get("/api/preflight/examples").json()
    assert len(examples) == 14
    assert "rotate" not in {item["id"] for item in examples}
    sample = next(item for item in examples if item["id"] == "discount")
    assert sample["prompt"] == prompt(EXERCISES["discount"])
    hostile = "<img src=x onerror=alert(1)>; __import__('os').system('no')"
    response = client.post("/api/preflight", json={"prompt": hostile})
    assert response.status_code == 200
    assert response.json()["mode"] == "offline_preflight"
    assert response.json()["live_model_calls"] == 0
    assert hostile not in response.text
    assert client.get("/api/history").json() == []
    assert client.post("/api/live-runs", json=response.json()).status_code == 423


@pytest.mark.parametrize(
    "changes",
    [
        {"prompt": ""},
        {"prompt": " \n\t"},
        {"prompt": "x" * 32769},
        {"context": "x" * 32769},
        {"generated_low": 0},
        {"generated_high": 4097},
        {"generated_low": 1024, "generated_high": 256},
        {"generated_low": True},
        {"generated_low": 1.5},
        {"selected_model": "unregistered-model"},
        {"approved": True},
    ],
)
def test_invalid_preview_requests_are_rejected(
    client: TestClient, changes: dict[str, object]
) -> None:
    """Bound inputs and scenarios rather than silently accepting a misleading plan."""
    assert (
        client.post(
            "/api/preflight", json={"prompt": "Write tests", **changes}
        ).status_code
        == 422
    )


def test_every_packaged_observation_matches_the_frozen_prompt() -> None:
    """Sanitized real evidence must stay attached to its actual request."""
    evidence = catalog()
    assert evidence.pricing_as_of == "2026-10-17"
    assert evidence.observed_on == "2026-10-17"
    assert "introductory rates through 2026-12-31" in evidence.pricing_note
    assert len(evidence.source_report_sha256) == 64
    for profile in evidence.profiles:
        assert len(profile.observations) == 3
        for row in profile.observations:
            assert (
                hashlib.sha256(prompt(EXERCISES[row.task_id]).encode()).hexdigest()
                == row.prompt_sha256
            )


@pytest.mark.parametrize(
    "task_id", [item.id for item in EXERCISES.values() if item.split == "development"]
)
def test_every_development_example_supports_preview_and_fixture_comparison(
    client: TestClient, task_id: str
) -> None:
    """Every offered use case works locally without manufacturing pilot evidence."""
    examples = client.get("/api/preflight/examples").json()
    example = next(item for item in examples if item["id"] == task_id)
    for role in ("compact", "strong"):
        response = client.post(
            "/api/preflight",
            json={
                "prompt": example["prompt"],
                "selected_model": role,
                "carbon_scenario": {},
            },
        )
        assert response.status_code == 200
        result = response.json()
        assert result["live_model_calls"] == 0
        assert result["carbon"]["carbon_g"] is None
        assert [row["role"] for row in result["models"] if row["selected"]] == [role]
        for model in result["models"]:
            assert model["illustrative_impact"]["impact"]["carbon_g"]["high"] > 0
            assert (model["quality"]["matched_observation"] is not None) == (
                task_id in {"clamp", "discount", "merge"}
            )
    compared = client.post("/api/compare", json={"task_id": task_id})
    assert compared.status_code == 200
    assert compared.json()["baseline"]["accepted"] is True


def test_original_three_eight_evidence_is_preserved_separately() -> None:
    """Switching the planner must not relabel or delete original model responses."""
    resource = (
        Path(__file__).parents[1] / "src/carbontrace/resources/preflight-evidence.json"
    )
    historical = json.loads(resource.read_text())
    assert historical["profiles"][1]["model_id"] == "gemini-3.8-flash"
    assert len(historical["profiles"][1]["observations"]) == 3
    assert historical["profiles"][0]["observations"][0]["generated_tokens"] == 240
    assert catalog().profiles[0].observations[0].generated_tokens == 313


def test_partial_evidence_cannot_borrow_the_other_models_observations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing model stays unobserved even for an otherwise identical prompt."""
    import carbontrace.preflight as preflight

    original = catalog()
    partial = original.model_copy(
        update={
            "profiles": [
                original.profiles[0],
                original.profiles[1].model_copy(update={"observations": []}),
            ]
        }
    )
    monkeypatch.setattr(preflight, "catalog", lambda: partial)
    result = build_preflight(PreflightRequest(prompt=prompt(EXERCISES["clamp"])))
    assert result.models[0].quality.matched_observation is not None
    assert result.models[1].quality.matched_observation is None
    assert result.models[1].input_tokens.basis == "utf8_planning_heuristic"
    assert "no matching quality" in result.guidance
