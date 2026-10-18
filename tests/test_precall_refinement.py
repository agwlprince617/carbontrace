"""Pre-call quality decisions and single-model plans; no network or paid execution."""

from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_live_comparison import FakeProvider, draft, evaluate

from carbontrace.benchmark import prompt
from carbontrace.benchmarks import EXERCISES
from carbontrace.live_compare_cli import execute
from carbontrace.live_comparison import LiveComparisonStore, prepare_quote, quote_task
from carbontrace.preflight import (
    PreflightRequest,
    WorkloadReference,
    build_preflight,
    precall_decision,
)


def test_exact_request_has_actionable_candidate_before_any_execution() -> None:
    result = build_preflight(PreflightRequest(prompt=prompt(EXERCISES["clamp"])))
    decision = result.decision
    assert decision.status == "supported_candidate"
    assert decision.evidence_scope == "exact_paired_prompt"
    assert decision.recommended_role == "compact"
    assert decision.selected_matches_recommendation is False
    assert result.live_model_calls == 0 and result.carbon.carbon_g is None
    assert any("cost" in reason for reason in decision.reasons)


@pytest.mark.parametrize(
    "changes",
    [{"context": "New requirements"}, {"prompt": "Write tests for unfamiliar code"}],
)
def test_unfamiliar_context_cannot_borrow_saved_quality(
    changes: dict[str, str],
) -> None:
    request = {"prompt": prompt(EXERCISES["clamp"]), **changes}
    decision = build_preflight(PreflightRequest.model_validate(request)).decision
    assert decision.status == "insufficient_quality_evidence"
    assert decision.recommended_role is None and decision.recommended_model_id is None


@pytest.mark.parametrize(
    "failures,expected", [(0, "compact"), (1, "strong"), (2, None)]
)
def test_quality_gates_override_price_and_environment(
    failures: int, expected: str | None
) -> None:
    result = build_preflight(
        PreflightRequest(
            prompt=prompt(EXERCISES["clamp"]),
            research_reference=WorkloadReference(workload="chat.light"),
        )
    )
    models = list(result.models)
    for index in range(failures):
        observation = models[index].quality.matched_observation
        assert observation is not None
        models[index] = models[index].model_copy(
            update={
                "quality": models[index].quality.model_copy(
                    update={
                        "matched_observation": observation.model_copy(
                            update={"accepted": False, "detected": 0}
                        )
                    }
                )
            }
        )
    decision = precall_decision(models, "strong", result.research_reference)
    assert decision.recommended_role == expected
    if failures == 2:
        assert decision.status == "no_passing_candidate"
    models[1] = models[1].model_copy(
        update={
            "quality": models[1].quality.model_copy(
                update={"matched_observation": None}
            )
        }
    )
    assert (
        precall_decision(models, "strong", result.research_reference).evidence_scope
        == "partial_exact_prompt"
    )


@pytest.mark.parametrize(
    "role,model,cost",
    [
        ("compact", "gemini-3.5-flash-lite", "0.00019"),
        ("strong", "gemini-3.7-flash", "0.00075"),
    ],
)
def test_selected_execution_sends_only_one_exact_payload(
    tmp_path: Path, role: str, model: str, cost: str
) -> None:
    request = PreflightRequest.model_validate(
        {
            "prompt": "Write tests for def double(x): return 2*x",
            "context": "Use pytest, no external libraries.",
            "selected_model": role,
        }
    )
    store = LiveComparisonStore(tmp_path)
    view: dict[str, Any] = store.create_selected(request)
    quote = view["quote"]
    assert quote["schema_version"] == 2
    assert (
        quote["generation_calls"]
        == quote["token_count_calls"]
        == quote["metadata_reads"]
        == 1
    )
    assert [row["model_id"] for row in quote["models"]] == [model]
    assert quote["exact_payload"] == request.visible_payload()
    assert quote["research"] is None
    assert quote_task(quote) is None
    provider = FakeProvider()
    state = store.reserve(quote["id"], view["approval_phrase"])
    result = asyncio.run(execute(store, quote["id"], state, provider, None))
    assert result["status"] == "completed"
    assert [kind for kind, _ in provider.calls] == ["metadata", "count", "generate"]
    assert {called for _, called in provider.calls} == {model}
    assert set(provider.payloads) == {request.visible_payload()}
    assert result["known_catalog_cost_usd"] == cost
    assert result["recommended_model"] is None
    assert len(result["responses"]) == 1
    assert store.view(quote["id"])["result"] == result


def test_owned_exact_request_keeps_its_contract_and_quote_cost(
    client: TestClient, tmp_path: Path
) -> None:
    request = PreflightRequest(
        prompt=prompt(EXERCISES["clamp"]),
        selected_model="compact",
        research_reference=WorkloadReference(workload="chat.light"),
    )
    response = client.post(
        "/api/selected-runs/prepare", json=request.model_dump(mode="json")
    )
    assert response.status_code == 200
    quote = response.json()["quote"]
    assert quote["estimated_cost_usd"] == "0.0114688"
    assert quote["stress_cost_usd"] == "0.0217088"
    assert quote["precall_decision"]["recommended_role"] == "compact"
    assert quote_task(quote) == "clamp"
    store = LiveComparisonStore(tmp_path)
    view: dict[str, Any] = store.create_selected(request)
    state = store.reserve(view["quote"]["id"], view["approval_phrase"])
    result = asyncio.run(
        execute(store, view["quote"]["id"], state, FakeProvider(), evaluate)
    )
    assert (
        result["status"] == "completed"
        and result["responses"][0]["quality"]["accepted"]
    )
    assert (
        result["recommended_model"] is None
    )  # no post-hoc comparison with an uncalled model
    assert (
        client.post(
            "/api/selected-runs/prepare",
            json=request.model_dump(mode="json"),
            headers={"origin": "https://elsewhere.example"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/selected-runs/prepare",
            json={"prompt": "x" * 32768, "context": "y" * 200},
        ).status_code
        == 422
    )
    with pytest.raises(ValueError):
        quote_task({"draft": {"quality_task": "unsupported"}})


def test_completed_legacy_comparison_hash_is_unchanged() -> None:
    legacy = prepare_quote(
        draft(
            "clamp",
            instruction="Write clear pytest tests, covering normal inputs, boundary conditions and the documented error behaviour. Return Python code only.",
        ),
        "bb3f0181799b4f61a6f596285f9eec93",
        datetime.fromisoformat("2026-10-17T18:06:25.529107+00:00"),
    )
    assert (
        legacy["plan_sha256"]
        == "317e3391ea97c87e11a4192974abf5ee76e33fe687ec08b2d67306bfc9eb686a"
    )
    assert legacy["generation_calls"] == 2
    assert quote_task(legacy) == "clamp"
    assert Decimal(str(legacy["estimated_cost_usd"])) == Decimal("0.0483328")
