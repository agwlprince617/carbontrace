"""Offline tests of exact quotes, one-shot execution and honest evidence boundaries."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from carbontrace import live_compare_cli as cli
from carbontrace.benchmarks import EXERCISES
from carbontrace.exercise import Exercise
from carbontrace.live_comparison import LiveComparisonStore, LiveDraft, prepare_quote
from carbontrace.live_smoke import Generation, RunError, Usage
from carbontrace.sandbox import SandboxError


def draft(task: str | None = None, **changes: Any) -> LiveDraft:
    values: dict[str, Any] = {
        "instruction": "Write pytest boundary and error tests.",
        "source_code": (
            EXERCISES[task].source if task else "def double(x):\n    return x * 2\n"
        ),
        "quality_task": task,
        "workload": "chat.light",
    }
    return LiveDraft.model_validate({**values, **changes})


def test_public_view_does_not_disclose_store_path(tmp_path: Path) -> None:
    """A custom store location never becomes a browser command or export field."""
    private_directory = tmp_path / "private-user" / "private-project"
    store = LiveComparisonStore(private_directory)
    created = store.create(draft())
    view = store.view(str(cast(dict[str, Any], created["quote"])["id"]))
    serialized = json.dumps(view)
    assert str(private_directory) not in serialized
    assert "private-user" not in serialized
    assert "command" not in view
    assert view["execution_mode"] == "local_cli"


def reserved(
    tmp_path: Path, task: str | None = None
) -> tuple[LiveComparisonStore, str, dict[str, Any]]:
    store = LiveComparisonStore(tmp_path / "live")
    view: dict[str, Any] = store.create(draft(task))
    run_id = view["quote"]["id"]
    return store, run_id, store.reserve(run_id, view["approval_phrase"])


class FakeProvider:
    """Synthetic transport only. Never represents a real Gemini result."""

    def __init__(self, fault: str = "") -> None:
        self.fault = fault
        self.calls: list[tuple[str, str]] = []
        self.payloads: list[str] = []

    async def model(self, model_id: str) -> str:
        self.calls.append(("metadata", model_id))
        return "publishers/google/models/" + (
            "sibling" if self.fault == "metadata" else model_id
        )

    async def count(self, model_id: str, text: str) -> int | None:
        self.calls.append(("count", model_id))
        self.payloads.append(text)
        return (
            None
            if self.fault == "missing_count"
            else 4097 if self.fault == "large" else 300
        )

    async def generate(self, model_id: str, text: str) -> Generation:
        self.calls.append(("generate", model_id))
        self.payloads.append(text)
        if self.fault == "timeout":
            raise TimeoutError("secret provider detail must not leak")
        if self.fault == "cancel":
            raise asyncio.CancelledError
        usage = Usage(
            input_tokens=300,
            candidate_tokens=40,
            total_tokens=340,
            cached_tokens=1 if self.fault == "cache" else None,
        )
        if self.fault == "usage":
            usage = Usage()
        return Generation(
            text=(
                "```python\ninvalid\n```"
                if self.fault == "code"
                else "from subject import clamp\ndef test_example():\n    assert clamp(5, 0, 10) == 5\n"
            ),
            model_version="sibling" if self.fault == "version" else model_id,
            finish_reason="MAX_TOKENS" if self.fault == "finish" else "STOP",
            usage=usage,
            elapsed_seconds=0.25,
        )


def evaluate(exercise: Exercise, code: str) -> dict[str, object]:
    """Synthetic evaluator report tests contracts without executing model code."""
    outcome = {"status": "passed", "tests": 4, "failures": 0, "errors": 0, "skipped": 0}
    return {
        "task_id": exercise.id,
        "image_id": cli.IMAGE,
        "suite_sha256": hashlib.sha256(code.encode()).hexdigest(),
        "reference": outcome,
        "mutations": {
            m.name: {**outcome, "status": "failed", "failures": 1}
            for m in exercise.mutations
        },
        "accepted": True,
    }


def test_prepare_api_sends_nothing_and_export_preserves_request(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/live-comparisons/prepare", json=draft().model_dump(mode="json")
    )
    assert response.status_code == 200
    view = response.json()
    quote = view["quote"]
    assert view["result"] is None
    assert view["new_calls_from_this_read"] == 0
    assert view["status"] == "awaiting_terminal_approval"
    assert (
        quote["generation_calls"]
        == quote["token_count_calls"]
        == quote["metadata_reads"]
        == 2
    )
    assert quote["estimated_cost_usd"] == "0.0483328"
    assert quote["stress_cost_usd"] == "0.0892928"
    assert quote["allowance_usd"] == "0.10"
    assert quote["draft"]["source_code"] == draft().source_code
    assert (
        quote["research"]["models"][0]["evidence"]["energy_wh_mean"] == "0.062106712990"
    )
    assert client.get(f"/api/live-comparisons/{quote['id']}").json() == view
    exported = client.get(f"/api/live-comparisons/{quote['id']}/export")
    assert exported.json() == view
    assert "attachment" in exported.headers["content-disposition"]
    assert client.get("/api/history").json() == []
    assert client.post("/api/live-runs", json={"approved": True}).status_code == 423


def test_api_origin_validation_missing_and_invalid_id(client: TestClient) -> None:
    assert (
        client.post(
            "/api/live-comparisons/prepare",
            json=draft().model_dump(mode="json"),
            headers={"origin": "https://other.example"},
        ).status_code
        == 403
    )
    assert client.get("/api/live-comparisons/" + "a" * 32).status_code == 404
    assert client.get("/api/live-comparisons/invalid").status_code == 422
    assert (
        client.post(
            "/api/live-comparisons/prepare",
            json={**draft().model_dump(mode="json"), "approved": True},
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"instruction": " "},
        {"source_code": " "},
        {"context": "x" * 32768},
        {"quality_task": "clamp"},
        {"workload": "arbitrary"},
        {"grid_g_per_kwh": -1},
    ],
)
def test_unreviewed_source_and_bad_inputs_rejected(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        draft(**changes)


def test_approval_hash_tamper_expiry_and_result_binding(tmp_path: Path) -> None:
    store = LiveComparisonStore(tmp_path)
    view: dict[str, Any] = store.create(draft("clamp"))
    run_id = view["quote"]["id"]
    with pytest.raises(ValueError, match="Approval"):
        store.reserve(run_id, "APPROVE anything")
    assert not store.path(run_id, "result").exists()
    path = store.path(run_id, "plan")
    raw = json.loads(path.read_text())
    raw["models"][0]["model_id"] = "sibling"
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="changed"):
        store.load(run_id)
    quote = prepare_quote(draft(), run_id, datetime.now(UTC) - timedelta(days=2))
    path.write_text(json.dumps(quote))
    with pytest.raises(ValueError, match="expired"):
        store.reserve(run_id, f"APPROVE {quote['plan_sha256']}")
    store.path(run_id, "result").write_text('{"plan_sha256":"wrong"}')
    with pytest.raises(ValueError, match="Results"):
        store.view(run_id)
    with pytest.raises(ValueError, match="Invalid"):
        store.path("../secret", "plan")


def test_run_once_three_slots_and_private_file_modes(tmp_path: Path) -> None:
    store = LiveComparisonStore(tmp_path)
    for slot in range(4):
        view: dict[str, Any] = store.create(draft())
        run_id = view["quote"]["id"]
        if slot == 3:
            with pytest.raises(ValueError, match="Three"):
                store.reserve(run_id, view["approval_phrase"])
            assert store.view(run_id)["status"] == "stopped"
        else:
            store.reserve(run_id, view["approval_phrase"])
            with pytest.raises(FileExistsError):
                store.reserve(run_id, view["approval_phrase"])
            assert store.path(run_id, "result").stat().st_mode & 0o777 == 0o600
    assert store.view(run_id)["remaining_demo_runs"] == 0


@pytest.mark.parametrize("task", [None, "clamp", "discount", "merge"])
def test_success_same_payload_usage_cost_and_quality(
    tmp_path: Path, task: str | None
) -> None:
    store, run_id, state = reserved(tmp_path, task)
    provider = FakeProvider()
    result = asyncio.run(
        cli.execute(store, run_id, state, provider, evaluate if task else None)
    )
    assert result["status"] == "completed"
    assert len(provider.calls) == 6
    assert [kind for kind, _ in provider.calls] == [
        "metadata",
        "count",
        "metadata",
        "count",
        "generate",
        "generate",
    ]
    assert len(set(provider.payloads)) == 1
    assert result["billing_uncertain"] is False
    assert result["actual_carbon_g"] is None
    assert Decimal(result["known_catalog_cost_usd"]) == Decimal("0.00094")
    assert len(result["responses"]) == 2
    assert result["responses"][0]["usage"]["thinking_tokens"] is None
    assert result["responses"][0]["effective_usage"]["thinking_tokens"] == 0
    assert result["recommended_model"] == ("gemini-3.5-flash-lite" if task else None)
    with pytest.raises(RunError, match="reservation"):
        asyncio.run(cli.execute(store, run_id, result, provider, None))
    assert len(provider.calls) == 6


@pytest.mark.parametrize(
    "fault,generations",
    [
        ("metadata", 0),
        ("large", 0),
        ("missing_count", 0),
        ("timeout", 1),
        ("usage", 1),
        ("version", 1),
        ("cache", 1),
    ],
)
def test_failure_stops_without_retry(
    tmp_path: Path, fault: str, generations: int
) -> None:
    store, run_id, state = reserved(tmp_path)
    provider = FakeProvider(fault)
    result = asyncio.run(cli.execute(store, run_id, state, provider, None))
    assert result["status"] == "stopped"
    assert sum(kind == "generate" for kind, _ in provider.calls) == generations
    assert result["billing_uncertain"] is (generations > 0)
    assert "secret provider detail" not in json.dumps(result)
    assert store.view(run_id)["result"] == result


@pytest.mark.parametrize("fault", ["finish", "code"])
def test_unusable_suite_is_not_a_passing_candidate(tmp_path: Path, fault: str) -> None:
    store, run_id, state = reserved(tmp_path, "clamp")
    provider = FakeProvider(fault)
    result = asyncio.run(cli.execute(store, run_id, state, provider, evaluate))
    assert result["status"] == "completed"
    assert result["recommended_model"] is None
    assert all(not row["quality"]["accepted"] for row in result["responses"])
    assert Decimal(result["known_catalog_cost_usd"]) > 0


def test_quality_provenance_and_strict_gate_override_claim(tmp_path: Path) -> None:
    def weak(exercise: Exercise, code: str) -> dict[str, object]:
        report: dict[str, Any] = evaluate(exercise, code)
        report["reference"]["skipped"] = 1
        return report

    store, run_id, state = reserved(tmp_path, "clamp")
    result = asyncio.run(cli.execute(store, run_id, state, FakeProvider(), weak))
    assert result["status"] == "completed" and result["recommended_model"] is None
    with pytest.raises(RunError, match="provenance"):
        cli.checked_quality(EXERCISES["clamp"], "code", {})


@pytest.mark.parametrize("kind", ["none", "infrastructure"])
def test_missing_or_failed_runner_stops_next_generation(
    tmp_path: Path, kind: str
) -> None:
    def fail(_exercise: Exercise, _code: str) -> dict[str, object]:
        raise SandboxError("Container unavailable")

    store, run_id, state = reserved(tmp_path, "clamp")
    provider = FakeProvider()
    result = asyncio.run(
        cli.execute(
            store, run_id, state, provider, fail if kind == "infrastructure" else None
        )
    )
    assert result["status"] == "stopped"
    assert sum(kind == "generate" for kind, _ in provider.calls) == 1
    assert result["billing_uncertain"] is False


@pytest.mark.parametrize(
    "task,project",
    [(None, "wrong"), ("clamp", "carbontrace-511814"), (None, "carbontrace-511814")],
)
def test_run_setup_without_real_clients(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, task: str | None, project: str
) -> None:
    store = LiveComparisonStore(tmp_path)
    view: dict[str, Any] = store.create(draft(task))
    provider = FakeProvider()
    monkeypatch.setattr(
        "carbontrace.live_compare_cli.Credentials.from_authorized_user_file",
        lambda *_args: SimpleNamespace(quota_project_id=project),
    )

    class Context:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_args: object) -> None:
            pass

    monkeypatch.setattr(
        "carbontrace.live_compare_cli.genai.Client",
        lambda **_kwargs: SimpleNamespace(aio=Context()),
    )
    monkeypatch.setattr(cli, "GeminiProvider", lambda _client: provider)
    monkeypatch.setattr(
        "carbontrace.live_compare_cli.ContainerRunner.preflight", lambda _self: None
    )
    monkeypatch.setattr(
        "carbontrace.live_compare_cli.ContainerRunner.evaluate",
        lambda _self, exercise, code: evaluate(exercise, code),
    )
    result = asyncio.run(cli.run(store, view["quote"]["id"], view["approval_phrase"]))
    assert result["status"] == (
        "completed" if project == "carbontrace-511814" else "stopped"
    )
    if project == "wrong":
        assert provider.calls == []


def test_setup_error_and_cli_terminal_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = LiveComparisonStore(tmp_path)
    view: dict[str, Any] = store.create(draft())

    def broken(*_args: object) -> None:
        raise OSError("do not disclose credentials path")

    monkeypatch.setattr(
        "carbontrace.live_compare_cli.Credentials.from_authorized_user_file", broken
    )
    result = asyncio.run(cli.run(store, view["quote"]["id"], view["approval_phrase"]))
    assert result["status"] == "stopped" and "do not disclose" not in str(result)
    view = cast(dict[str, Any], store.create(draft()))
    args = ["--directory", str(tmp_path), "--id", view["quote"]["id"]]
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    with pytest.raises(SystemExit):
        cli.main(args)
    assert not store.path(view["quote"]["id"], "result").exists()
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _message: "cancel")
    with pytest.raises(SystemExit):
        cli.main(args)
    assert not store.path(view["quote"]["id"], "result").exists()
    monkeypatch.setattr("builtins.input", lambda _message: view["approval_phrase"])
    with pytest.raises(SystemExit, match="1"):
        cli.main(args)
    assert store.view(view["quote"]["id"])["status"] == "stopped"


def test_cancelled_generation_is_consumed_and_billing_uncertain(tmp_path: Path) -> None:
    store, run_id, state = reserved(tmp_path)
    provider = FakeProvider("cancel")
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(cli.execute(store, run_id, state, provider, None))
    view: dict[str, Any] = store.view(run_id)
    assert view["result"]["status"] == "stopped"
    assert view["result"]["billing_uncertain"] is True
    assert sum(kind == "generate" for kind, _ in provider.calls) == 1
    with pytest.raises(FileExistsError):
        store.reserve(run_id, view["approval_phrase"])


def test_cancelled_setup_records_stopped_without_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = LiveComparisonStore(tmp_path)
    view: dict[str, Any] = store.create(draft())

    def cancel(*_args: object) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(
        "carbontrace.live_compare_cli.Credentials.from_authorized_user_file", cancel
    )
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(cli.run(store, view["quote"]["id"], view["approval_phrase"]))
    assert store.view(view["quote"]["id"])["status"] == "stopped"


def test_quality_failure_beats_lower_energy_reference(tmp_path: Path) -> None:
    calls = 0

    def first_fails(exercise: Exercise, code: str) -> dict[str, object]:
        nonlocal calls
        report: dict[str, Any] = evaluate(exercise, code)
        if calls == 0:
            report["mutations"] = {}
        calls += 1
        return report

    store, run_id, state = reserved(tmp_path, "clamp")
    result = asyncio.run(cli.execute(store, run_id, state, FakeProvider(), first_fails))
    assert result["status"] == "completed"
    assert result["recommended_model"] == "gemini-3.7-flash"
