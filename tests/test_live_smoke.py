"""Offline-only live-run safeguards with fake providers and mocked SDK transport."""

from __future__ import annotations

import asyncio
import hashlib
import json
import ssl
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import cast

import httpx
import pytest
from google import genai
from google.genai import types
from google.oauth2.credentials import Credentials

from carbontrace.exercise import Exercise
from carbontrace.live_smoke import (
    APPROVED_HASH,
    CONTINUATION_HASH,
    REPLACEMENT_HASH,
    GeminiProvider,
    Generation,
    Ledger,
    Plan,
    RunError,
    Usage,
    check_prior_evidence,
    client_http_options,
    execute,
    generation_config,
    http_options,
    load_approved_plan,
    main,
    run_live,
    user_adc,
)
from carbontrace.sandbox import ContainerRunner, SandboxError

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def approved_plan() -> Plan:
    """Load the actual human-approved immutable quote, without creating a client."""
    return load_approved_plan(
        ROOT / "docs/vertex-smoke-quote.json", ROOT / "docs/vertex-smoke-approval.json"
    )


def test_replacement_has_its_own_explicit_approval() -> None:
    """The failed attempt's receipt cannot authorize a replacement plan."""
    quote = ROOT / "docs/vertex-smoke-replacement-quote.json"
    with pytest.raises(RunError, match="human-approved plan"):
        load_approved_plan(quote, ROOT / "docs/vertex-smoke-approval.json")
    plan = load_approved_plan(
        quote, ROOT / "docs/vertex-smoke-replacement-approval.json"
    )
    assert plan.plan_sha256 == REPLACEMENT_HASH != APPROVED_HASH
    assert len(plan.requests) == 6


def test_continuation_approval_allows_only_the_unsent_five() -> None:
    """The continuation has distinct consent and preserves the paid first result."""
    quote = ROOT / "docs/vertex-smoke-continuation-quote.json"
    with pytest.raises(RunError, match="human-approved plan"):
        load_approved_plan(quote, ROOT / "docs/vertex-smoke-replacement-approval.json")
    plan = load_approved_plan(
        quote, ROOT / "docs/vertex-smoke-continuation-approval.json"
    )
    assert plan.plan_sha256 == CONTINUATION_HASH
    assert len(plan.requests) == 5 and plan.usage_policy == "protojson_v2"
    assert plan.requests[0].task_id == "clamp"
    assert plan.requests[0].model_role == "strong"
    assert plan.prior_catalog_cost_usd == Decimal("0.0006486")


@dataclass
class FakeProvider:
    """Deterministic unit-test provider; makes no network requests."""

    mode: str = "normal"
    calls: list[str] = field(default_factory=list)
    generated: int = 0

    async def model(self, model_id: str) -> str | None:
        """Return a public resource name or simulate metadata failure."""
        self.calls.append("metadata")
        return (
            None if self.mode == "metadata" else f"publishers/google/models/{model_id}"
        )

    async def count(self, model_id: str, text: str) -> int | None:
        """Return a known prompt count or simulate an invalid count."""
        self.calls.append("count")
        return None if self.mode == "count" else 100

    async def generate(self, model_id: str, text: str) -> Generation:
        """Return fake telemetry; no simulated result is labelled provider evidence."""
        self.calls.append("generate")
        self.generated += 1
        if self.mode == "timeout":
            raise TimeoutError("must not log secret request context")
        version = None if self.mode == "version" else model_id
        if self.mode == "version_change" and self.generated >= 3:
            version = model_id + "-changed"
        usage = Usage(
            input_tokens=100,
            candidate_tokens=200,
            thinking_tokens=300,
            cached_tokens=0,
            total_tokens=600,
        )
        if self.mode == "missing":
            usage = usage.model_copy(update={"cached_tokens": None})
        if self.mode == "breach":
            usage = usage.model_copy(
                update={"thinking_tokens": 4096, "total_tokens": 4396}
            )
        return Generation(
            "def test_example():\n    assert True\n",
            version,
            "MAX_TOKENS" if self.mode == "truncated" else "STOP",
            usage,
            0.25,
        )


def fake_quality(_exercise: Exercise, _code: str) -> dict[str, object]:
    """Stub only the evaluator boundary; unit tests never execute generated Python."""
    return {"accepted": True, "provenance": "unit_test_stub"}


def test_approval_hash_and_prompt_are_bound(
    approved_plan: Plan, tmp_path: Path
) -> None:
    """Changing a rate, model, limit, or receipt cannot reuse the recorded approval."""
    assert approved_plan.plan_sha256 == APPROVED_HASH
    quote = json.loads((ROOT / "docs/vertex-smoke-quote.json").read_text())
    quote["limits"]["generation_calls"] = 7
    modified = tmp_path / "quote.json"
    modified.write_text(json.dumps(quote))
    with pytest.raises(RunError, match="differs"):
        load_approved_plan(modified, ROOT / "docs/vertex-smoke-approval.json")
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({"plan_sha256": APPROVED_HASH, "decision": "denied"}))
    with pytest.raises(RunError, match="human approval"):
        load_approved_plan(ROOT / "docs/vertex-smoke-quote.json", receipt)


def test_six_calls_are_one_shot_and_all_costs_accounted(
    approved_plan: Plan, tmp_path: Path
) -> None:
    """Exactly two metadata, six counts, six generations; replay is refused."""
    provider = FakeProvider()
    ledger = Ledger(tmp_path, approved_plan)
    result = asyncio.run(execute(approved_plan, provider, ledger, fake_quality))
    assert result["status"] == "completed"
    assert provider.calls.count("generate") == 6
    assert provider.calls.count("metadata") == 2
    assert provider.calls.count("count") == 6
    assert Decimal(str(result["total_catalog_cost_usd"])) == Decimal("0.01554")
    assert json.loads(ledger.path.read_text()) == result
    with pytest.raises(RunError, match="replay"):
        Ledger(tmp_path, approved_plan)
    with pytest.raises(RunError, match="count exhausted"):
        ledger.dispatch("generate", "must-not-dispatch")


@pytest.mark.parametrize(
    "mode, generations",
    [
        ("metadata", 0),
        ("count", 0),
        ("timeout", 1),
        ("missing", 1),
        ("breach", 1),
        ("version", 1),
        ("version_change", 3),
    ],
)
def test_uncertain_outcomes_stop_without_retry(
    mode: str, generations: int, approved_plan: Plan, tmp_path: Path
) -> None:
    """An uncertain billable response remains unknown and prevents further work."""
    provider = FakeProvider(mode)
    result = asyncio.run(
        execute(approved_plan, provider, Ledger(tmp_path, approved_plan), fake_quality)
    )
    assert result["status"] == "stopped"
    assert provider.calls.count("generate") == generations
    if generations:
        assert result["total_catalog_cost_usd"] is None
    assert "secret request context" not in str(result)


def test_incomplete_and_rejected_suites_still_count_usage(
    approved_plan: Plan, tmp_path: Path
) -> None:
    """Quality failures cannot erase consumed inference or force an extra generation."""

    def rejected(_exercise: Exercise, _code: str) -> dict[str, object]:
        """Simulate actual fault-detection quality rejection."""
        return {"accepted": False, "reason": "Seeded faults survived"}

    for mode in ("normal", "truncated"):
        result = asyncio.run(
            execute(
                approved_plan,
                FakeProvider(mode),
                Ledger(tmp_path / mode, approved_plan),
                rejected,
            )
        )
        assert result["status"] == "completed"
        assert Decimal(str(result["total_catalog_cost_usd"])) > 0
        generations = cast(list[dict[str, object]], result["generations"])
        assert all(
            cast(dict[str, object], item["quality"])["accepted"] is False
            for item in generations
        )


def test_sandbox_failure_stops_further_spending(
    approved_plan: Plan, tmp_path: Path
) -> None:
    """A failed execution boundary prevents spending on candidates we cannot grade."""

    def unavailable(_exercise: Exercise, _code: str) -> dict[str, object]:
        """Simulate local runtime failure after static validation."""
        raise SandboxError("Runtime unavailable")

    provider = FakeProvider()
    result = asyncio.run(
        execute(approved_plan, provider, Ledger(tmp_path, approved_plan), unavailable)
    )
    assert result["status"] == "stopped" and provider.generated == 1
    assert result["total_catalog_cost_usd"] is not None


@pytest.mark.parametrize(
    "changes",
    [
        {"cached_tokens": None},
        {"cached_tokens": -1},
        {"cached_tokens": 101},
        {"total_tokens": 999},
        {"tool_tokens": 1},
        {"input_tokens": 4097},
    ],
)
def test_missing_or_inconsistent_usage_never_becomes_zero(
    changes: dict[str, int | None],
) -> None:
    """Omitted values are preserved and fail the conservative smoke protocol."""
    usage = Usage(
        input_tokens=100,
        candidate_tokens=200,
        thinking_tokens=300,
        cached_tokens=0,
        total_tokens=600,
    ).model_copy(update=changes)
    with pytest.raises(RunError):
        usage.checked()


def test_sdk_configuration_disables_hidden_extra_work() -> None:
    """Verify the exact installed SDK fields controlling retry and continuation."""
    options = http_options()
    assert options.retry_options and options.retry_options.attempts == 1
    assert options.api_version == "v1" and options.timeout == 60000
    config = generation_config()
    assert config.max_output_tokens == 4096 and config.candidate_count == 1
    assert config.automatic_continuation is False
    assert (
        config.automatic_function_calling and config.automatic_function_calling.disable
    )
    assert (
        config.thinking_config
        and config.thinking_config.thinking_level == types.ThinkingLevel.LOW
    )
    assert config.temperature is None and config.tools is None


def test_client_tls_keeps_certificate_and_hostname_verification() -> None:
    """The system-trust fix must never turn a certificate error into verify=False."""
    options = client_http_options()
    for arguments in (options.client_args, options.async_client_args):
        assert arguments is not None
        context = arguments["verify"]
        assert isinstance(context, ssl.SSLContext)
        assert context.verify_mode == ssl.CERT_REQUIRED
        assert context.check_hostname is True
    assert options.retry_options and options.retry_options.attempts == 1


def test_protojson_defaults_preserve_raw_metadata() -> None:
    """A real response shape omits zero scalars; only explicit v2 resolves them."""
    usage = Usage(input_tokens=162, candidate_tokens=240, total_tokens=402)
    with pytest.raises(RunError, match="Missing"):
        usage.checked()
    assert usage.checked("protojson_v2") == (162, 240)
    assert usage.thinking_tokens is None and usage.cached_tokens is None
    assert usage.effective("protojson_v2").thinking_tokens == 0


def test_reused_response_is_bound_to_ledger_and_prior_cost(
    approved_plan: Plan, tmp_path: Path
) -> None:
    """Offline evidence cannot silently change or erase the prior call's cost."""
    first = approved_plan.requests[0]
    row = {
        "task_id": first.task_id,
        "model_role": first.model_role,
        "model_id": first.model_id,
        "model_version": first.model_id,
        "prompt_sha256": first.prompt_sha256,
        "finish_reason": "STOP",
        "usage": {"input_tokens": 162, "candidate_tokens": 240, "total_tokens": 402},
    }
    content = json.dumps({"status": "stopped", "generations": [row]}).encode()
    path = tmp_path / f"{REPLACEMENT_HASH}.json"
    path.write_bytes(content)
    plan = approved_plan.model_copy(
        update={
            "usage_policy": "protojson_v2",
            "prior_catalog_cost_usd": Decimal("0.0006486"),
            "prior_ledger_sha256": hashlib.sha256(content).hexdigest(),
        }
    )
    check_prior_evidence(plan, tmp_path)
    with pytest.raises(RunError, match="estimate differs"):
        check_prior_evidence(
            plan.model_copy(update={"prior_catalog_cost_usd": Decimal(0)}), tmp_path
        )
    path.write_bytes(content + b" ")
    with pytest.raises(RunError, match="ledger differs"):
        check_prior_evidence(plan, tmp_path)


@pytest.mark.parametrize(
    "changes",
    [
        {"input_tokens": None},
        {"candidate_tokens": None},
        {"total_tokens": None},
        {"total_tokens": 403},
        {"thinking_tokens": -1},
        {"cached_tokens": 163},
        {"tool_tokens": 1},
    ],
)
def test_protojson_still_stops_on_unknown_or_inconsistent_usage(
    changes: dict[str, int | None],
) -> None:
    """Zero defaults cannot conceal missing main counters or unreconciled tokens."""
    usage = Usage(input_tokens=162, candidate_tokens=240, total_tokens=402)
    with pytest.raises(RunError):
        usage.model_copy(update=changes).checked("protojson_v2")


def test_remaining_five_never_regenerate_the_saved_candidate(
    approved_plan: Plan, tmp_path: Path
) -> None:
    """Continue only the unsent suffix and include the first response's estimate."""
    models = {
        role: rate.model_copy(update={"calls": 2 if role == "compact" else 3})
        for role, rate in approved_plan.models.items()
    }
    plan = approved_plan.model_copy(
        update={
            "requests": approved_plan.requests[1:],
            "models": models,
            "usage_policy": "protojson_v2",
            "prior_catalog_cost_usd": Decimal("0.0006486"),
        }
    )
    provider = FakeProvider("missing")
    ledger = Ledger(tmp_path, plan)
    result = asyncio.run(execute(plan, provider, ledger, fake_quality))
    assert result["status"] == "completed"
    assert provider.calls.count("generate") == provider.calls.count("count") == 5
    assert Decimal(str(result["total_catalog_cost_usd"])) == Decimal("0.0149086")
    generations = cast(list[dict[str, object]], result["generations"])
    assert not any(
        row["task_id"] == "clamp" and row["model_role"] == "compact"
        for row in generations
    )
    assert all(
        cast(dict[str, object], row["usage"])["cached_tokens"] is None
        for row in generations
    )
    with pytest.raises(RunError, match="count exhausted"):
        ledger.dispatch("generate", "unused")


@pytest.mark.parametrize("failure", [False, True])
def test_actual_sdk_uses_only_mock_transport(failure: bool) -> None:
    """Intercept the installed SDK HTTP boundary, including a retryable 503."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Never contact Google; return structurally realistic fake responses."""
        requests.append(request)
        if failure:
            return httpx.Response(
                503,
                json={
                    "error": {
                        "message": "offline injected error",
                        "status": "UNAVAILABLE",
                        "code": 503,
                    }
                },
            )
        if request.method == "GET":
            return httpx.Response(
                200, json={"name": "publishers/google/models/gemini-3.5-flash-lite"}
            )
        if request.url.path.endswith(":countTokens"):
            return httpx.Response(200, json={"totalTokens": 100})
        body = json.loads(request.content)
        assert body["generationConfig"]["maxOutputTokens"] == 4096
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [{"text": "assert True"}],
                        },
                        "finishReason": "STOP",
                    }
                ],
                "modelVersion": "gemini-3.5-flash-lite",
                "usageMetadata": {
                    "promptTokenCount": 100,
                    "candidatesTokenCount": 200,
                    "thoughtsTokenCount": 300,
                    "cachedContentTokenCount": 0,
                    "totalTokenCount": 600,
                },
            },
        )

    async def exercise_sdk() -> None:
        """Use static dummy credentials so even auth cannot make an external call."""
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as transport:
            options = client_http_options().model_copy(
                update={"httpx_async_client": transport}
            )
            async with genai.Client(
                enterprise=True,
                project="carbontrace-511814",
                location="global",
                credentials=cast(Callable[..., Credentials], Credentials)(
                    token="offline-unit-test-token"
                ),
                http_options=options,
            ).aio as client:
                provider = GeminiProvider(client)
                if failure:
                    with pytest.raises(Exception, match="503"):
                        await provider.generate(
                            "gemini-3.5-flash-lite", "offline fixture"
                        )
                    return
                assert await provider.model("gemini-3.5-flash-lite")
                assert (
                    await provider.count("gemini-3.5-flash-lite", "offline fixture")
                    == 100
                )
                result = await provider.generate(
                    "gemini-3.5-flash-lite", "offline fixture"
                )
                assert result.text == "assert True" and result.usage.checked() == (
                    100,
                    500,
                )

    asyncio.run(exercise_sdk())
    assert len(requests) == (1 if failure else 3)


def test_cli_refuses_unapproved_execution(tmp_path: Path) -> None:
    """Even an execution flag cannot replace an actual matching approval receipt."""
    with pytest.raises(SystemExit):
        main(
            [
                "--plan",
                str(ROOT / "docs/vertex-smoke-quote.json"),
                "--approval",
                str(tmp_path / "missing.json"),
                "--image",
                "invalid",
                "--execute-approved-smoke",
            ]
        )


def test_adc_is_local_user_only_and_quota_project_bound(
    approved_plan: Plan, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Use only fabricated credential fixtures; never inspect a user's real ADC."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    with pytest.raises(RunError, match="sign-in"):
        user_adc(approved_plan)
    credential_file = tmp_path / ".config/gcloud/application_default_credentials.json"
    credential_file.parent.mkdir(parents=True)
    fixture = {
        "type": "authorized_user",
        "client_id": "offline",
        "client_secret": "offline",
        "refresh_token": "offline",
        "quota_project_id": "wrong",
    }
    credential_file.write_text(json.dumps(fixture))
    with pytest.raises(RunError, match="quota project"):
        user_adc(approved_plan)
    fixture["quota_project_id"] = "carbontrace-511814"
    credential_file.write_text(json.dumps(fixture))
    assert user_adc(approved_plan).quota_project_id == approved_plan.project


def test_client_setup_failure_is_recorded_without_network(
    approved_plan: Plan, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Client construction failure cannot erase or automatically replay the ledger."""
    from carbontrace import live_smoke

    monkeypatch.setattr(ContainerRunner, "preflight", lambda _self: None)
    monkeypatch.setattr(live_smoke, "user_adc", lambda _plan: None)

    def missing_client(**_kwargs: object) -> None:
        """Fail before a provider client or external request exists."""
        raise RuntimeError("offline injected failure")

    monkeypatch.setattr(genai, "Client", missing_client)
    result = asyncio.run(run_live(approved_plan, tmp_path, "sha256:" + "a" * 64))
    assert result["status"] == "stopped"
    assert result["operations"] == []
    assert result["total_catalog_cost_usd"] == "0"
