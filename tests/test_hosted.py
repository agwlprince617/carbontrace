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
    MODEL_BUDGET_MICROUSD,
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
    reservation_microusd,
)
from carbontrace.live_smoke import Generation, Provider, Usage
from carbontrace.preflight import PreflightRequest

NOW = datetime(2026, 10, 18, tzinfo=UTC)
CONFIG = HostedSettings(b"x" * 32, NOW + timedelta(days=7))


class MemoryObjects:
    def __init__(self) -> None:
        self.items: dict[str, tuple[dict[str, Any], int]] = {
            f"budget/{POOL_EPOCH}.json": (
                {
                    "epoch": POOL_EPOCH,
                    "schema_version": 2,
                    "budget_microusd": MODEL_BUDGET_MICROUSD,
                    "runs": {},
                },
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


def approved(role: str = "compact", *, compare: bool = False) -> HostedApproval:
    plan = issue_quote(
        PreflightRequest.model_validate(
            {"prompt": "Write pytest tests for double(x).", "selected_model": role}
        ),
        CONFIG,
        NOW,
        compare_models=compare,
    )
    return HostedApproval(
        plan=plan,
        approval_hash=plan.quote["plan_sha256"],
        allowance_usd=Decimal(plan.quote["allowance_usd"]),
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
    quotes = [approved("strong").plan.quote for _ in range(80)]

    def reserve(quote: dict[str, Any]) -> bool:
        try:
            return HostedLedger(objects).reserve(quote)
        except HostedError:
            return False

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(reserve, quotes))
    assert 6 < sum(results) <= 59
    ledger = HostedLedger(objects)
    while Decimal(str(ledger.status()["remaining_usd"])) >= Decimal("0.067584"):
        ledger.reserve(approved("strong").plan.quote)
    assert ledger.status()["runs_reserved"] == 59
    assert Decimal(str(ledger.status()["remaining_usd"])) >= 0
    with pytest.raises(PoolExhausted):
        ledger.reserve(approved("strong").plan.quote)
    first = quotes[results.index(True)]
    assert HostedLedger(objects).reserve(first) is False
    with pytest.raises(HostedError, match="mismatch"):
        HostedLedger(objects).reserve({**first, "plan_sha256": "changed"})
    with pytest.raises(HostedError):
        HostedLedger(objects).receipt("../invalid")
    objects.items.clear()
    with pytest.raises(HostedError, match="not initialized"):
        HostedLedger(objects).status()


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
    assert ledger.status()["runs_reserved"] == 1


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
    assert ledger.status()["runs_reserved"] == 1
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
        assert client.get("/api/hosted/status").json()["remaining_usd"] == "4"
        assert "hosted-consent" not in client.get("/").text
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
            "allowance_usd": plan["quote"]["allowance_usd"],
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


def test_legacy_budget_migration_never_resets_usage() -> None:
    objects = MemoryObjects()
    key = f"budget/{POOL_EPOCH}.json"
    quotes = [approved(role).plan.quote for role in ("compact", "strong")]
    legacy: dict[str, Any] = {
        "epoch": POOL_EPOCH,
        "limit": 6,
        "runs": {
            quote["id"]: {
                "plan_sha256": quote["plan_sha256"],
                "model_id": quote["models"][0]["model_id"],
            }
            for quote in quotes
        },
    }
    objects.items[key] = legacy, 1
    ledger = HostedLedger(objects)
    assert ledger.status()["runs_reserved"] == 2
    assert objects.items[key][0] == legacy  # A status read never writes.
    assert ledger.reserve(quotes[0]) is False  # Old ID remains consumed.
    ledger.reserve(approved().plan.quote)
    persisted = objects.items[key][0]
    assert persisted["schema_version"] == 2 and "limit" not in persisted
    assert persisted["runs"].keys() >= legacy["runs"].keys()
    assert ledger.status()["runs_reserved"] == 3
    assert ledger.status()["reserved_usd"] == str(
        Decimal(
            2 * reservation_microusd("gemini-3.5-flash-lite")
            + reservation_microusd("gemini-3.7-flash")
        )
        / 1_000_000
    )
    assert HostedLedger(objects).status() == ledger.status()


@pytest.mark.parametrize("damage", ["amount", "model", "budget", "legacy_overflow"])
def test_budget_corruption_stops_before_provider(damage: str) -> None:
    objects, provider = MemoryObjects(), FakeProvider()
    ledger = HostedLedger(objects)
    ledger.reserve(approved().plan.quote)
    key = f"budget/{POOL_EPOCH}.json"
    meter = objects.items[key][0]
    row = next(iter(meter["runs"].values()))
    if damage == "amount":
        row["reserved_microusd"] = 0
    elif damage == "model":
        row["model_id"] = "unknown"
    elif damage == "budget":
        meter["budget_microusd"] = 5_000_000
    else:
        meter.pop("schema_version")
        meter["limit"] = 6
        meter["runs"] = {str(i): row for i in range(7)}
    with pytest.raises(HostedError, match="verified"):
        asyncio.run(execute_hosted(approved().plan.quote, ledger, provider.context))
    assert not provider.calls


def test_above_stress_usage_stops_new_runs() -> None:
    ledger, provider = HostedLedger(MemoryObjects()), FakeProvider()
    provider.usage = Usage(
        input_tokens=10, candidate_tokens=30_000, total_tokens=30_010
    )
    result = asyncio.run(
        execute_hosted(approved().plan.quote, ledger, provider.context)
    )
    assert result["status"] == "failed"
    assert "limit breach" in result["error"]
    assert ledger.status()["halted"] is True
    prior = list(provider.calls)
    with pytest.raises(PoolExhausted):
        asyncio.run(execute_hosted(approved().plan.quote, ledger, provider.context))
    assert provider.calls == prior


class PairedProvider(FakeProvider):
    def __init__(self) -> None:
        super().__init__()
        self.payloads: list[tuple[str, str]] = []
        self.fail_second = False

    async def generate(self, model_id: str, text: str) -> Generation:
        self.payloads.append((model_id, text))
        self.failure = self.fail_second and model_id == "gemini-3.7-flash"
        output = 20 if model_id == "gemini-3.5-flash-lite" else 40
        self.usage = Usage(
            input_tokens=10, candidate_tokens=output, total_tokens=10 + output
        )
        return await super().generate(model_id, text)


def test_pair_exact_quote_atomic_reservation_and_no_repeat() -> None:
    approval = approved(compare=True)
    quote = check_approval(approval, CONFIG, NOW)
    assert quote["generation_calls"] == quote["token_count_calls"] == 2
    assert quote["reservation_usd"] == "0.089293"
    assert quote["allowance_usd"] == "0.089293"
    assert quote["estimated_cost_usd"] == "0.0483328"
    assert len(quote["models"]) == 2
    objects, provider = MemoryObjects(), PairedProvider()
    ledger = HostedLedger(objects)
    result = asyncio.run(execute_hosted(quote, ledger, provider.context))
    assert provider.calls == ["client", "count", "generate", "count", "generate"]
    assert provider.payloads == [
        (model["model_id"], quote["exact_payload"]) for model in quote["models"]
    ]
    assert result["status"] == "completed"
    assert [
        row["response"]["effective_usage"]["candidate_tokens"]
        for row in result["responses"]
    ] == [20, 40]
    assert result["comparison"]["complete"] is True
    assert result["comparison"]["lower_observed_cost_model"] == "gemini-3.5-flash-lite"
    assert result["comparison"]["recommended_model_id"] is None
    assert result["actual_carbon_g"] is None
    assert ledger.status()["reserved_usd"] == "0.089293"
    assert ledger.status()["runs_reserved"] == 1
    assert ledger.status()["generations_reserved"] == 2
    assert (
        asyncio.run(execute_hosted(quote, HostedLedger(objects), provider.context))
        == result
    )
    assert provider.calls.count("generate") == 2


def test_pair_budget_cannot_partially_dispatch() -> None:
    objects, provider = MemoryObjects(), PairedProvider()
    ledger = HostedLedger(objects)
    for _ in range(58):
        ledger.reserve(approved("strong").plan.quote)
    remaining = Decimal(str(ledger.status()["remaining_usd"]))
    assert Decimal("0.067584") <= remaining < Decimal("0.089293")
    with pytest.raises(PoolExhausted):
        asyncio.run(
            execute_hosted(approved(compare=True).plan.quote, ledger, provider.context)
        )
    assert provider.calls == []
    assert Decimal(str(ledger.status()["remaining_usd"])) == remaining


@pytest.mark.parametrize("fail_second", [False, True])
def test_pair_failure_preserves_first_output_and_never_retries(
    fail_second: bool,
) -> None:
    ledger, provider = HostedLedger(MemoryObjects()), PairedProvider()
    provider.fail_second = fail_second
    if not fail_second:
        provider.count_value = 4097
    quote = approved(compare=True).plan.quote
    result = asyncio.run(execute_hosted(quote, ledger, provider.context))
    assert result["status"] == ("partial_failure" if fail_second else "failed")
    assert result["comparison"]["complete"] is False
    assert result["comparison"]["recommended_model_id"] is None
    assert "lower_observed_cost_model" not in result["comparison"]
    assert "secret token" not in str(result)
    assert result["responses"][0]["status"] == (
        "completed" if fail_second else "failed"
    )
    assert result["responses"][1]["status"] == (
        "failed" if fail_second else "not_started"
    )
    prior = list(provider.calls)
    asyncio.run(execute_hosted(quote, ledger, provider.context))
    assert provider.calls == prior
    assert ledger.status()["reserved_usd"] == "0.089293"


def test_pair_corrupt_model_list_stops_execution() -> None:
    objects = MemoryObjects()
    ledger = HostedLedger(objects)
    ledger.reserve(approved(compare=True).plan.quote)
    meter = objects.items[f"budget/{POOL_EPOCH}.json"][0]
    row = next(iter(meter["runs"].values()))
    row["model_ids"] = ["gemini-3.5-flash-lite", "gemini-3.5-flash-lite"]
    with pytest.raises(HostedError, match="verified"):
        ledger.status()


def test_paired_route_only_prepares_until_explicit_execute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CARBONTRACE_MODE", "hosted-live")
    ledger, provider = HostedLedger(MemoryObjects()), PairedProvider()
    config = HostedSettings(b"p" * 32, datetime.now(UTC) + timedelta(days=1))
    monkeypatch.setattr(
        hosted_cloud,
        "settings",
        lambda: config,
    )
    monkeypatch.setattr(hosted_cloud, "cloud_ledger", lambda: ledger)
    monkeypatch.setattr(hosted_cloud, "cloud_provider", provider.context)
    with TestClient(create_app()) as client:
        plan = client.post(
            "/api/hosted/quote", json={"prompt": "Write tests", "compare_models": True}
        ).json()
        assert len(plan["quote"]["models"]) == 2
        assert not provider.calls
        assert ledger.status()["reserved_usd"] == "0"
        result = client.post(
            "/api/hosted/execute",
            json={
                "plan": plan,
                "approval_hash": plan["quote"]["plan_sha256"],
                "allowance_usd": plan["quote"]["allowance_usd"],
                "agreed": True,
            },
        )
        assert result.status_code == 200 and len(result.json()["responses"]) == 2
