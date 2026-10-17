"""Recorded Gemini workflow and inert suite inspection never create new model calls."""

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import carbontrace.workflow as workflow
from carbontrace.decision import SuiteEvidence, saved_evidence
from carbontrace.workflow import saved_run


@pytest.mark.parametrize("task", ["clamp", "discount", "merge"])
def test_workflow_shows_original_prompt_cloud_operations_and_full_run_scope(
    client: TestClient, task: str
) -> None:
    response = client.get(f"/api/decision/tasks/{task}/workflow")
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "saved_run_replay" and data["new_model_calls"] == 0
    assert len(data["requests"]) == 2
    digest = hashlib.sha256(data["exact_prompt"].encode()).hexdigest()
    assert all(
        row["prompt_sha256"] == digest and row["task_id"] == task
        for row in data["requests"]
    )
    assert {r["model_id"] for r in data["requests"]} == {
        "gemini-3.5-flash-lite",
        "gemini-3.7-flash",
    }
    assert all(
        r["metadata_status"]
        == r["token_count_status"]
        == r["generation_status"]
        == "completed"
        for r in data["requests"]
    )
    assert data["run"]["source_report_sha256"] == saved_evidence().source_report_sha256
    assert data["run"]["project"] == "carbontrace-511814"
    assert data["run"]["region"] == "global"
    assert data["run"]["generation_calls"] == data["run"]["token_count_calls"] == 6
    assert data["run"]["metadata_reads"] == 2
    assert data["run"]["thinking_level"] == "LOW"
    assert data["run"]["maximum_generated_tokens"] == 4096
    assert data["run"]["automatic_retries"] == 0
    assert not data["run"]["automatic_continuation"]
    assert Decimal(data["run"]["full_run_catalog_cost_usd"]) == Decimal("0.01010385")
    assert client.get("/api/history").json() == []
    assert client.post("/api/live-runs", json=data).status_code == 423


@pytest.mark.parametrize(
    "record", saved_evidence().records, ids=lambda r: f"{r.task_id}-{r.model_id}"
)
def test_inline_preview_is_exact_checked_text_and_hash(
    client: TestClient, record: SuiteEvidence
) -> None:
    response = client.get(
        f"/api/decision/tasks/{record.task_id}/suite/{record.model_id}/preview"
    )
    assert response.status_code == 200
    data = response.json()
    assert (
        data["sha256"]
        == hashlib.sha256(data["source_code"].encode()).hexdigest()
        == record.suite_sha256
    )
    download = client.get(
        f"/api/decision/tasks/{record.task_id}/suite/{record.model_id}"
    )
    assert data["source_code"].encode() == download.content
    assert "Viewing does not execute" in data["note"]


@pytest.mark.parametrize(
    "path",
    [
        "/api/decision/tasks/rotate/workflow",
        "/api/decision/tasks/clamp/suite/gemini-3.8-flash/preview",
    ],
)
def test_replay_rejects_unowned_tasks_and_sibling_models(
    client: TestClient, path: str
) -> None:
    assert client.get(path).status_code == 422


def test_workflow_hash_is_checked_before_showing_recorded_stages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved_run.cache_clear()
    monkeypatch.setattr(workflow, "TRACE_SHA256", "0" * 64)
    try:
        with pytest.raises(ValueError, match="integrity"):
            saved_run()
    finally:
        saved_run.cache_clear()


@pytest.mark.parametrize(
    "kind,match",
    [
        ("report", "different reports"),
        ("pairs", "pairs differ"),
        ("version", "identity differs"),
        ("prompt", "identity differs"),
        ("counts", "totals differ"),
    ],
)
def test_source_pairs_and_operation_counts_cannot_be_mixed(
    monkeypatch: pytest.MonkeyPatch, kind: str, match: str
) -> None:
    saved_run.cache_clear()
    path = Path(workflow.__file__).parent / "resources/decision-workflow.json"
    data = json.loads(path.read_text())
    if kind == "report":
        data["source_report_sha256"] = "0" * 64
    elif kind == "pairs":
        data["requests"][1] = data["requests"][0]
    elif kind == "version":
        data["requests"][0]["response_model_version"] = "gemini-3.8-flash"
    elif kind == "prompt":
        data["requests"][0]["prompt_sha256"] = "0" * 64
    else:
        data["generation_calls"] = 7
    content = json.dumps(data).encode()
    original = Path.read_bytes

    def read_bytes(target: Path) -> bytes:
        return content if target == path else original(target)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    monkeypatch.setattr(workflow, "TRACE_SHA256", hashlib.sha256(content).hexdigest())
    try:
        with pytest.raises(ValueError, match=match):
            saved_run()
    finally:
        saved_run.cache_clear()
