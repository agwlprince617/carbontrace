"""HTTP contracts, local persistence, and fail-closed execution."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from carbontrace.domain import CompareRequest, HardwareScenario
from carbontrace.engine import build_comparison
from carbontrace.store import EvidenceStore


def test_home_assets_and_project_status(client: TestClient) -> None:
    """The interface works locally and advertises the true execution mode."""
    response = client.get("/")
    assert response.status_code == 200
    assert "Right-size the model" in response.text
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    for asset in (
        "app.css",
        "app.js",
        "api-client.mjs",
        "research.mjs",
        "decision.mjs",
        "workflow.mjs",
        "live-comparison.mjs",
        "mark.svg",
    ):
        assert client.get(f"/static/{asset}").status_code == 200
    health = client.get("/api/health").json()
    assert health["live_enabled"] is False
    assert health["live_calls"] == 0
    assert health["project"] == "carbontrace-511814"


def test_recorded_demo_is_portable_and_read_only(client: TestClient) -> None:
    """Recorded live evidence works with an empty local run store."""
    response = client.get("/api/demo-comparison")
    assert response.status_code == 200
    view = response.json()
    assert view["read_only"] is True
    assert view["execution_mode"] == "recorded_evidence"
    assert view["status"] == "completed"
    assert view["quote"]["plan_sha256"] == (
        "317e3391ea97c87e11a4192974abf5ee76e33fe687ec08b2d67306bfc9eb686a"
    )
    assert view["result"]["plan_sha256"] == view["quote"]["plan_sha256"]
    assert len(view["result"]["responses"]) == 2
    assert view["result"]["known_catalog_cost_usd"] == "0.0046848"
    assert "command" not in view and "approval_phrase" not in view
    assert "/Users/" not in response.text
    assert "/home/" not in response.text
    assert client.get("/api/demo-comparison/export").json() == view
    assert client.post("/api/demo-comparison").status_code == 405
    assert client.get("/api/health").json()["live_calls"] == 0


def test_compare_persist_retrieve_and_export(
    client: TestClient, scenario: HardwareScenario
) -> None:
    """A comparison preserves its full provenance through local storage/export."""
    assert client.get("/api/history").json() == []
    response = client.post(
        "/api/compare",
        json={
            "task_id": "merge",
            "minimum_detection": 100,
            "scenario": scenario.model_dump(),
        },
    )
    assert response.status_code == 200
    record = response.json()
    run_id = record["id"]
    assert record["outcome"] == "escalated"
    assert client.get(f"/api/runs/{run_id}").json() == record
    assert client.get("/api/history").json()[0] == record
    exported = client.get(f"/api/runs/{run_id}/export")
    assert exported.json() == record
    assert "attachment" in exported.headers["content-disposition"]
    assert client.get("/api/runs/does-not-exist").status_code == 404
    assert client.get("/api/runs/does-not-exist/export").status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {"task_id": "unknown"},
        {"minimum_detection": 0},
        {"minimum_detection": 101},
        {"python_code": "print('must not execute')"},
        {"scenario": {"pue": 1}},
    ],
)
def test_invalid_inputs_rejected(
    client: TestClient, payload: dict[str, object]
) -> None:
    """The API accepts exercise identifiers, not executable uploads."""
    assert client.post("/api/compare", json=payload).status_code == 422


def test_downloads_and_unknown_ids(client: TestClient) -> None:
    """Only curated references and profiles can be exported."""
    assert "def clamp" in client.get("/api/tasks/clamp/source").text
    suite = client.get("/api/tasks/clamp/suite/compact")
    assert "pytest" in suite.text
    assert "attachment" in suite.headers["content-disposition"]
    assert client.get("/api/tasks/unknown/source").status_code == 422
    assert client.get("/api/tasks/clamp/suite/unknown").status_code == 422
    tasks = client.get("/api/tasks").json()
    assert len(tasks) == 14
    assert client.get("/api/benchmark").json()["holdout_functions"] == 6
    assert client.get("/api/tasks/rotate/source").status_code == 422
    assert client.post("/api/compare", json={"task_id": "rotate"}).status_code == 422
    assert all(item["mutations"] == 4 for item in tasks)


def test_live_endpoint_cannot_be_unlocked_by_environment(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A flag is not financial authorization or a connected provider."""
    monkeypatch.setenv("LIVE_CALLS_ENABLED", "true")
    response = client.post("/api/live-runs", json={"approved": True})
    assert response.status_code == 423
    assert "cost" in response.json()["detail"]


def test_host_validation(client: TestClient) -> None:
    """The development app is served only under loopback and test hostnames."""
    assert client.get("/", headers={"host": "unexpected.example"}).status_code == 400


def test_history_is_bounded_and_ids_are_parameters(tmp_path: Path) -> None:
    """History is capped at twenty and hostile strings are never interpreted."""
    store = EvidenceStore(tmp_path / "local.sqlite3")
    store.initialize()
    for _ in range(22):
        store.save(build_comparison(CompareRequest()))
    assert len(store.recent()) == 20
    assert store.get("' OR 1=1 --") is None
