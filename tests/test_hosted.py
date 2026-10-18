"""Offline checks for public-pool limits, exact approval, and no repeat dispatch."""

from __future__ import annotations

import asyncio
import copy
import threading
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from carbontrace import hosted_cloud
from carbontrace.app import create_app
from carbontrace.hosted import (
    POOL_EPOCH,
    Conflict,
    HostedApproval,
    HostedError,
    HostedLedger,
    HostedSettings,
    PoolExhausted,
    check_approval,
    execute_hosted,
    issue_quote,
)
from carbontrace.live_smoke import Generation, Provider, Usage
from carbontrace.preflight import PreflightRequest

NOW = datetime(2026, 10, 18, tzinfo=UTC)
CONFIG = HostedSettings(b"x" * 32, NOW + timedelta(days=7))


class MemoryObjects:
    def __init__(self) -> None:
        self.items: dict[str, tuple[dict[str, Any], int]] = {
            f"budget/{POOL_EPOCH}.json": (
                {"epoch": POOL_EPOCH, "limit": 6, "runs": {}},
                1,
            )
        }
        self.lock = threading.Lock()
        self.fail_receipt = False

    def read(self, name: str) -> tuple[dict[str, Any], int] | None:
        with self.lock:
            return copy.deepcopy(self.items.get(name))

    def write(
        self, name: str, value: dict[str, Any], generation: int | None = None
    ) -> None:
        with self.lock:
            if name.startswith("runs/") and self.fail_receipt:
                raise HostedError("Storage down")
            old = self.items.get(name, ({}, 0))[1]
            if generation is not None and generation != old:
                raise Conflict("Changed")
            self.items[name] = copy.deepcopy(value), old + 1


def approved(role: str = "compact") -> HostedApproval:
    plan = issue_quote(
        PreflightRequest.model_validate(
            {"prompt": "Write pytest tests for double(x).", "selected_model": role}
        ),
        CONFIG,
        NOW,
    )
    return HostedApproval(
        plan=plan,
        approval_hash=plan.quote["plan_sha256"],
        allowance_usd=Decimal("0.10"),
        agreed=True,
    )


class FakeProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.count_value: int | None = 10
        self.failure = False
        self.version: str | None = None
        self.usage = Usage(input_tokens=10, candidate_tokens=20, total_tokens=30)

    async def model(self, model_id: str) -> str:
        raise AssertionError("Metadata is not needed for a hosted run")

    async def count(self, model_id: str, text: str) -> int | None:
        self.calls.append("count")
        return self.count_value

    async def generate(self, model_id: str, text: str) -> Generation:
        self.calls.append("generate")
        if self.failure:
            raise RuntimeError("secret token must never escape")
        return Generation(
            "assert double(2) == 4", self.version or model_id, "STOP", self.usage, 0.2
        )

    @asynccontextmanager
    async def context(self) -> AsyncIterator[Provider]:
        self.calls.append("client")
        yield self


def test_approval_tamper_expiry_and_consent() -> None:
    approval = approved()
    quote = check_approval(approval, CONFIG, NOW)
    assert quote["generation_calls"] == 1 and quote["metadata_reads"] == 0
    assert quote["quality_task"] is None
    assert quote["exact_payload"] == "Write pytest tests for double(x)."
    with pytest.raises(HostedError, match="expired"):
        check_approval(approval, CONFIG, NOW + timedelta(minutes=11))
    for update in (
        {"agreed": False},
        {"allowance_usd": "0.09"},
        {"approval_hash": "0" * 64},
    ):
        with pytest.raises(HostedError, match="Explicit approval"):
            check_approval(approval.model_copy(update=update), CONFIG, NOW)
    approval.plan.quote["exact_payload"] = "different"
    with pytest.raises(HostedError, match="changed"):
        check_approval(approval, CONFIG, NOW)
    with pytest.raises(PoolExhausted):
        issue_quote(PreflightRequest(prompt="x"), CONFIG, CONFIG.expires_at)
    with pytest.raises(HostedError):
        HostedSettings(b"short", CONFIG.expires_at)


def test_global_pool_concurrent_and_persistent() -> None:
    objects = MemoryObjects()
    quotes = [approved().plan.quote for _ in range(20)]

    def reserve(quote: dict[str, Any]) -> bool:
        try:
            return HostedLedger(objects).reserve(quote)
        except HostedError:
            return False

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(reserve, quotes))
    assert sum(results) == 6
    assert HostedLedger(objects).remaining() == 0
    with pytest.raises(PoolExhausted):
        HostedLedger(objects).reserve(approved().plan.quote)
    first = quotes[results.index(True)]
    assert HostedLedger(objects).reserve(first) is False
    with pytest.raises(HostedError, match="mismatch"):
        HostedLedger(objects).reserve({**first, "plan_sha256": "changed"})
    with pytest.raises(HostedError):
        HostedLedger(objects).receipt("../invalid")
    objects.items.clear()
    with pytest.raises(HostedError, match="not initialized"):
        HostedLedger(objects).remaining()


@pytest.mark.parametrize("role", ["compact", "strong"])
def test_one_execution_replay_and_real_usage(role: str) -> None:
    ledger, provider = HostedLedger(MemoryObjects()), FakeProvider()
    quote = approved(role).plan.quote
    result = asyncio.run(execute_hosted(quote, ledger, provider.context))
    assert result["status"] == "completed"
    assert result["response"]["quality"] == "not_evaluated"
    assert result["response"]["raw_usage"]["thinking_tokens"] is None
    assert result["response"]["effective_usage"]["thinking_tokens"] == 0
    assert result["actual_carbon_g"] is None
    assert provider.calls == ["client", "count", "generate"]
    assert asyncio.run(execute_hosted(quote, ledger, provider.context)) == result
    assert provider.calls == ["client", "count", "generate"]
    assert ledger.remaining() == 5


@pytest.mark.parametrize(
    "failure", ["count", "provider", "version", "usage", "cache", "storage"]
)
def test_failure_consumes_reservation_without_retry(failure: str) -> None:
    objects, provider = MemoryObjects(), FakeProvider()
    ledger = HostedLedger(objects)
    if failure == "count":
        provider.count_value = 4097
    if failure == "provider":
        provider.failure = True
    if failure == "version":
        provider.version = "other-model"
    if failure == "usage":
        provider.usage = Usage(input_tokens=1)
    if failure == "cache":
        provider.usage = Usage(
            input_tokens=10, candidate_tokens=20, total_tokens=30, cached_tokens=1
        )
    if failure == "storage":
        objects.fail_receipt = True
    quote = approved().plan.quote
    if failure == "storage":
        with pytest.raises(HostedError):
            asyncio.run(execute_hosted(quote, ledger, provider.context))
        assert not provider.calls
    else:
        result = asyncio.run(execute_hosted(quote, ledger, provider.context))
        assert result["status"] == "failed"
        assert "secret token" not in str(result)
        assert provider.calls.count("generate") == (0 if failure == "count" else 1)
    assert ledger.remaining() == 5
    asyncio.run(execute_hosted(quote, ledger, provider.context))
    assert provider.calls.count("generate") <= 1


def test_hosted_app_keeps_local_routes_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CARBONTRACE_MODE", "hosted-live")
    ledger = HostedLedger(MemoryObjects())
    provider = FakeProvider()
    current_config = HostedSettings(b"k" * 32, datetime.now(UTC) + timedelta(days=1))
    monkeypatch.setattr(hosted_cloud, "settings", lambda: current_config)
    monkeypatch.setattr(hosted_cloud, "cloud_ledger", lambda: ledger)
    monkeypatch.setattr(hosted_cloud, "cloud_provider", provider.context)
    with TestClient(create_app()) as client:
        assert 'id="hosted-prepare"' in client.get("/").text
        assert client.get("/api/health").json()["live_enabled"]
        assert client.get("/api/hosted/status").json()["remaining"] == 6
        assert client.post("/api/live-runs", json={}).status_code == 423
        assert (
            client.post(
                "/api/hosted/quote",
                json={"prompt": "x"},
                headers={"origin": "https://evil.example"},
            ).status_code
            == 403
        )
        plan = client.post("/api/hosted/quote", json={"prompt": "Write tests"}).json()
        assert not provider.calls
        request = {
            "plan": plan,
            "approval_hash": plan["quote"]["plan_sha256"],
            "allowance_usd": "0.10",
            "agreed": True,
        }
        result = client.post("/api/hosted/execute", json=request)
        assert result.status_code == 200 and result.json()["status"] == "completed"
        assert (
            client.get(f"/api/hosted/runs/{plan['quote']['id']}").json()
            == result.json()
        )
        assert client.get("/api/hosted/runs/" + "0" * 32).status_code == 404
        request["agreed"] = False
        assert client.post("/api/hosted/execute", json=request).status_code == 503
    monkeypatch.setenv("CARBONTRACE_MODE", "local")
    with TestClient(create_app()) as client:
        assert client.get("/api/hosted/status").status_code == 423


def test_cloud_storage_preconditions_and_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CARBONTRACE_QUOTE_KEY", raising=False)
    with pytest.raises(HostedError):
        hosted_cloud.settings()
    monkeypatch.delenv("CARBONTRACE_LEDGER_BUCKET", raising=False)
    with pytest.raises(HostedError):
        hosted_cloud.cloud_ledger()
    cloud = hosted_cloud.CloudObjects("private-bucket")
    session = Mock()
    cloud.session = session
    response = session.request.return_value
    response.status_code = 404
    assert cloud.read("missing") is None
    response.status_code = 200
    response.json.return_value = {"a": 1}
    response.headers = {"x-goog-generation": "123"}
    assert cloud.read("object") == ({"a": 1}, 123)
    cloud.write("object", {"a": 2}, 123)
    assert (
        session.request.call_args.kwargs["headers"]["x-goog-if-generation-match"]
        == "123"
    )
    cloud.write("new", {}, 0)
    assert (
        session.request.call_args.kwargs["headers"]["x-goog-if-generation-match"] == "0"
    )
    response.status_code = 412
    with pytest.raises(Conflict):
        cloud.write("new", {}, 0)
    response.status_code = 403
    with pytest.raises(HostedError):
        cloud.read("object")
    with pytest.raises(HostedError):
        cloud.write("object", {})
    response.status_code = 200
    response.headers = {}
    with pytest.raises(HostedError):
        cloud.read("object")
    session.request.side_effect = RuntimeError("secret")
    with pytest.raises(HostedError, match="unavailable"):
        cloud.read("object")
