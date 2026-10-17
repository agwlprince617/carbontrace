"""Task decisions use real packaged evidence; paired branches use synthetic unit data."""

from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import carbontrace.decision as decision
from carbontrace.decision import (
    DecisionRequest,
    EvidenceBundle,
    GateExecution,
    SuiteEvidence,
    build_decision,
    saved_evidence,
)


def synthetic_pair(compact_passes: bool, strong_passes: bool) -> EvidenceBundle:
    """Create test-only outcomes; these never become saved provider observations."""
    bundle = saved_evidence()
    original = bundle.records[0]
    rows = []
    for model_id, passes, cost in [
        ("gemini-3.5-flash-lite", compact_passes, "0.0006486"),
        ("gemini-3.7-flash", strong_passes, "0.005"),
    ]:
        data = original.model_dump()
        data.update(model_id=model_id, model_version=model_id, catalog_cost_usd=cost)
        if not passes:
            first = next(iter(data["mutations"]))
            data["mutations"][first] = {
                "status": "passed",
                "tests": 8,
                "failures": 0,
                "errors": 0,
                "skipped": 0,
            }
        rows.append(SuiteEvidence.model_validate(data))
    return bundle.model_copy(update={"records": rows})


@pytest.mark.parametrize("task", ["clamp", "discount", "merge"])
def test_existing_evidence_uses_exact_paired_responses(
    client: TestClient, task: str
) -> None:
    response = client.post(
        "/api/decision", json={"task_id": task, "workload": "chat.light"}
    )
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "both_passed"
    assert result["recommended_model"] == "gemini-3.5-flash-lite"
    assert result["models"][0]["gate"] == "passed"
    assert (
        result["models"][0]["detected_faults"]
        == result["models"][0]["total_faults"]
        == 4
    )
    assert result["models"][1]["gate"] == "passed"
    assert result["models"][1]["detected_faults"] == 4
    assert result["models"][1]["evidence"]["model_id"] == "gemini-3.7-flash"
    assert all(row["available"] for row in result["reference"]["models"])
    assert result["reference"]["request"]["sessions"] == 1
    assert result["live_model_calls"] == 0
    assert result["models"][0]["evidence"]["input_tokens"] > 0
    assert (
        result["evidence_source_report_sha256"]
        == "be2c0077bda69abd8ba475178ea5fd1b595ccb4dfbb65bbfd152b67c0ae6854f"
    )
    assert client.get("/api/history").json() == []
    assert client.post("/api/live-runs", json=result).status_code == 423


@pytest.mark.parametrize(
    "compact,strong,status,chosen",
    [
        (True, True, "both_passed", "gemini-3.5-flash-lite"),
        (False, True, "one_passed", "gemini-3.7-flash"),
        (True, False, "one_passed", "gemini-3.5-flash-lite"),
        (False, False, "neither_passed", None),
    ],
)
def test_quality_gate_precedes_environmental_choice(
    compact: bool, strong: bool, status: str, chosen: str | None
) -> None:
    result = build_decision(
        DecisionRequest(workload="chat.light"), synthetic_pair(compact, strong)
    )
    assert result.status == status
    assert result.recommended_model == chosen
    assert result.known_comparison_cost_usd == Decimal("0.0056486")
    first, second = (row.total_energy_wh for row in result.reference.models)
    assert first is not None and second is not None and first < second


def test_zero_grid_does_not_make_a_failing_model_acceptable() -> None:
    result = build_decision(
        DecisionRequest(workload="chat.light", grid_g_per_kwh=Decimal(0)),
        synthetic_pair(False, True),
    )
    assert result.recommended_model == "gemini-3.7-flash"
    assert all(row.operational_carbon_g == 0 for row in result.reference.models)
    assert result.reference.models[0].total_energy_wh == Decimal("0.062106712990")


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "inconclusive", "failures": 1},
        {"errors": 1},
        {"skipped": 1},
        {"tests": 0},
        {"failures": 0},
        {"status": "passed"},
    ],
)
def test_errors_skips_and_inconclusive_checks_do_not_count_as_detected(
    changes: dict[str, object],
) -> None:
    check = GateExecution.model_validate(
        {
            "status": "failed",
            "tests": 8,
            "failures": 1,
            "errors": 0,
            "skipped": 0,
            **changes,
        }
    )
    assert not check.detected


def test_reference_failure_blocks_candidate_even_when_mutants_fail() -> None:
    row = saved_evidence().records[0]
    failed = row.model_copy(
        update={"reference": row.reference.model_copy(update={"failures": 1})}
    )
    assert not failed.accepted


@pytest.mark.parametrize(
    "changes",
    [
        {"prompt_sha256": "0" * 64},
        {"model_version": "gemini-3.8-flash"},
        {"model_id": "gemini-3.8-flash"},
        {"mutations": {}},
    ],
)
def test_bad_model_prompt_or_incomplete_gate_cannot_borrow_evidence(
    changes: dict[str, object],
) -> None:
    row = saved_evidence().records[0].model_dump()
    with pytest.raises(ValidationError):
        SuiteEvidence.model_validate({**row, **changes})


def test_snapshot_integrity_is_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    saved_evidence.cache_clear()
    monkeypatch.setattr(decision, "EVIDENCE_SHA256", "0" * 64)
    try:
        with pytest.raises(ValueError, match="integrity"):
            saved_evidence()
    finally:
        saved_evidence.cache_clear()


@pytest.mark.parametrize(
    "changes",
    [
        {"task_id": "rotate"},
        {"task_id": "parse_bool"},
        {"workload": "auto"},
        {"grid_g_per_kwh": -1},
        {"grid_g_per_kwh": 2001},
        {"prompt": "run code"},
        {"approved": True},
        {"evidence": []},
    ],
)
def test_web_decision_cannot_execute_or_import_arbitrary_results(
    client: TestClient, changes: dict[str, object]
) -> None:
    assert (
        client.post(
            "/api/decision", json={"workload": "chat.light", **changes}
        ).status_code
        == 422
    )


def test_missing_pair_blocks_a_recommendation() -> None:
    """A test-only missing record cannot make the other model win by default."""
    bundle = saved_evidence()
    partial = bundle.model_copy(
        update={
            "records": [r for r in bundle.records if r.model_id != "gemini-3.7-flash"]
        }
    )
    result = build_decision(DecisionRequest(workload="chat.light"), partial)
    assert result.status == "awaiting_pair"
    assert result.recommended_model is None
    assert result.models[1].evidence is None


@pytest.mark.parametrize("task", ["clamp", "discount", "merge"])
@pytest.mark.parametrize("model", ["gemini-3.5-flash-lite", "gemini-3.7-flash"])
def test_downloaded_suite_matches_the_checked_bytes(
    client: TestClient, task: str, model: str
) -> None:
    """Downloads are inert text, bound to the exact evaluated suite hash."""
    import hashlib

    response = client.get(f"/api/decision/tasks/{task}/suite/{model}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert ".txt" in response.headers["content-disposition"]
    row = next(
        r for r in saved_evidence().records if r.task_id == task and r.model_id == model
    )
    assert hashlib.sha256(response.content).hexdigest() == row.suite_sha256


def test_unknown_model_cannot_download_a_sibling_suite(client: TestClient) -> None:
    assert (
        client.get("/api/decision/tasks/clamp/suite/gemini-3.8-flash").status_code
        == 422
    )


def test_decision_task_list_is_narrow_and_static(client: TestClient) -> None:
    assert [task["id"] for task in client.get("/api/decision/tasks").json()] == [
        "clamp",
        "discount",
        "merge",
    ]


def test_download_requires_saved_record(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import carbontrace.app as application

    empty = saved_evidence().model_copy(update={"records": []})
    monkeypatch.setattr(application, "saved_evidence", lambda: empty)
    assert (
        client.get("/api/decision/tasks/clamp/suite/gemini-3.7-flash").status_code
        == 404
    )


def test_changed_suite_cannot_be_downloaded_as_checked(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import carbontrace.app as application

    directory = tmp_path / "resources/decision-suites"
    directory.mkdir(parents=True)
    (directory / "clamp-gemini-3.5-flash-lite.txt").write_text("unverified replacement")
    monkeypatch.setattr(application, "PACKAGE", tmp_path)
    assert (
        client.get("/api/decision/tasks/clamp/suite/gemini-3.5-flash-lite").status_code
        == 503
    )
