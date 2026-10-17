"""Explicit, one-shot CLI for the human-approved Vertex AI smoke experiment.

Importing this module, starting the web app, and running tests never creates a
provider client. The approval receipt records out-of-band human consent; it is
not a public authorization API or protection against the local filesystem owner.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import ssl
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal, Protocol, cast

from google import genai
from google.genai import types
from google.oauth2.credentials import Credentials
from pydantic import BaseModel, ConfigDict, Field
from truststore import SSLContext

from carbontrace.benchmark import manifest, prompt, run_plan
from carbontrace.benchmarks import EXERCISES
from carbontrace.exercise import Exercise
from carbontrace.sandbox import ContainerRunner, SandboxError, validate_suite

Role = Literal["compact", "strong"]
UsagePolicy = Literal["strict_v1", "protojson_v2", "protojson_full_v3"]
APPROVED_HASH = "b12276de602c9314c206828d3a8154f306e1a3c26d7c7c227d7ec05c259fcd8f"
REPLACEMENT_HASH = "3572cb926c4309fe3c27e7adc9dadc40980351cb56c29787f8fd25d0ea8c9a18"
CONTINUATION_HASH = "6145bd52e78c3ec890d80a1c5adeaf84836126f9284b2b114c70d9c5632c8607"
APPROVAL_REPLIES = {
    "7aa444d8bedcfd2c2ca8e73facc7d277d1a404d207e2ffb4a775c78cf2ecad16": "Approve six-generation comparison",
    APPROVED_HASH: "Approve setup and six-generation test",
    REPLACEMENT_HASH: "Approve replacement six-generation test",
    CONTINUATION_HASH: "Approve remaining five generations",
}


class RunError(RuntimeError):
    """A failed precondition or stop rule; no automatic retry is permitted."""


class Frozen(BaseModel):
    """Typed execution fields; informational quote fields remain covered by hash."""

    model_config = ConfigDict(frozen=True, extra="ignore", allow_inf_nan=False)


class Rate(Frozen):
    """Uncached catalog token rates; not a carbon coefficient."""

    id: str
    input_usd_per_million: Decimal = Field(ge=0)
    generated_usd_per_million: Decimal = Field(ge=0)
    calls: int = Field(ge=1, le=3)


class RequestSpec(Frozen):
    """One request bound to its original source-only prompt."""

    task_id: Literal["clamp", "discount", "merge"]
    model_role: Role
    model_id: str
    prompt_sha256: str
    repeat: Literal[0]


class Plan(Frozen):
    """The exact execution-relevant fields of the approved, immutable quote."""

    project: Literal["carbontrace-511814"]
    location: Literal["global"]
    api_version: Literal["v1"]
    plan_sha256: str
    benchmark_sha256: str
    models: dict[Role, Rate]
    requests: list[RequestSpec]
    usage_policy: UsagePolicy = "strict_v1"
    prior_catalog_cost_usd: Decimal = Field(
        default=Decimal(0), ge=0, le=Decimal("0.50")
    )
    prior_ledger_sha256: str | None = None


def load_approved_plan(path: Path, receipt_path: Path) -> Plan:
    """Check actual recorded consent, full quote hash, and every prompt binding."""
    raw = json.loads(path.read_text())
    claimed = raw.pop("plan_sha256", None)
    actual = hashlib.sha256(
        json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    receipt = json.loads(receipt_path.read_text())
    if (
        actual not in APPROVAL_REPLIES
        or claimed != actual
        or receipt.get("plan_sha256") != actual
    ):
        raise RunError("Quote differs from the human-approved plan")
    if (
        receipt.get("decision") != "approved"
        or receipt.get("human_reply") != APPROVAL_REPLIES[actual]
    ):
        raise RunError("Missing recorded human approval")
    plan = Plan.model_validate(dict(raw, plan_sha256=actual))
    if plan.benchmark_sha256 != manifest()["sha256"]:
        raise RunError("Benchmark changed after approval")
    expected = run_plan()["requests"]
    assert isinstance(expected, list)
    if plan.usage_policy == "protojson_v2":
        expected = expected[1:]
    if len(plan.requests) != len(expected) or len(plan.models) != 2:
        raise RunError("Unexpected request/model count")
    for role, rate in plan.models.items():
        if rate.calls != sum(request.model_role == role for request in plan.requests):
            raise RunError("Model call allowance differs from the request list")
    for request, original in zip(plan.requests, expected, strict=True):
        text = prompt(EXERCISES[request.task_id])
        if (
            request.prompt_sha256 != hashlib.sha256(text.encode()).hexdigest()
            or request.model_id != plan.models[request.model_role].id
            or request.task_id != original["task_id"]
            or request.model_role != original["model_role"]
        ):
            raise RunError("Request or source-only prompt changed")
    return plan


class Usage(Frozen):
    """Missing counters stay null; the smoke plan stops on unknown usage."""

    input_tokens: int | None = None
    candidate_tokens: int | None = None
    thinking_tokens: int | None = None
    cached_tokens: int | None = None
    total_tokens: int | None = None
    tool_tokens: int | None = None

    def effective(self, policy: UsagePolicy = "strict_v1") -> Usage:
        """Resolve only documented implicit-zero fields under an explicit policy."""
        if policy == "strict_v1":
            return self
        # Vertex v1 proto3 int32 scalars omit defaults in JSON. Keep primary
        # counters mandatory and retain the original nullable fields in evidence.
        return self.model_copy(
            update={
                name: 0 if getattr(self, name) is None else getattr(self, name)
                for name in ("thinking_tokens", "cached_tokens", "tool_tokens")
            }
        )

    def checked(self, policy: UsagePolicy = "strict_v1") -> tuple[int, int]:
        """Require main counters, nonnegative values, reconciled totals and caps."""
        values = self.effective(policy)
        required = (
            values.input_tokens,
            values.candidate_tokens,
            values.thinking_tokens,
            values.cached_tokens,
            values.total_tokens,
        )
        if any(value is None or value < 0 for value in required):
            raise RunError("Missing or negative usage counter; stop without retry")
        inputs, candidates, thinking, cached, total = cast(
            tuple[int, int, int, int, int], required
        )
        if (
            cached > inputs
            or total != inputs + candidates + thinking
            or values.tool_tokens not in (None, 0)
        ):
            raise RunError("Inconsistent usage or unexpected tool tokens")
        if inputs > 4096 or candidates + thinking > 4096:
            raise RunError("Observed input/generated token limit breach")
        return inputs, candidates + thinking


@dataclass(frozen=True)
class Generation:
    """Sanitized generation evidence; excludes credentials and HTTP headers."""

    text: str
    model_version: str | None
    finish_reason: str | None
    usage: Usage
    elapsed_seconds: float


class Provider(Protocol):
    """Only three explicit operations; no fallback, retry, or grading methods."""

    async def model(self, model_id: str) -> str | None:
        """Read one exact model's metadata."""
        ...

    async def count(self, model_id: str, text: str) -> int | None:
        """Count the exact prompt before generating."""
        ...

    async def generate(self, model_id: str, text: str) -> Generation:
        """Generate one candidate with the approved settings."""
        ...


def http_options(timeout_ms: int = 60_000) -> types.HttpOptions:
    """Pin stable API and disable SDK retries, including transient HTTP errors."""
    return types.HttpOptions(
        api_version="v1",
        timeout=timeout_ms,
        retry_options=types.HttpRetryOptions(attempts=1),
    )


def client_http_options() -> types.HttpOptions:
    """Use OS-managed trust for HTTPS, without global SSL patches or new roots."""
    context = SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    return http_options().model_copy(
        update={
            "client_args": {"verify": context},
            "async_client_args": {"verify": context},
        }
    )


def generation_config() -> types.GenerateContentConfig:
    """Disable hidden continuation/function calls and leave sampling at defaults."""
    return types.GenerateContentConfig(
        max_output_tokens=4096,
        candidate_count=1,
        thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
        automatic_continuation=False,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        response_modalities=["TEXT"],
    )


@dataclass
class GeminiProvider:
    """The SDK adapter; its caller owns and closes the explicit async client."""

    client: genai.client.AsyncClient

    async def model(self, model_id: str) -> str | None:
        """Read metadata without generating content."""
        result = await self.client.models.get(
            model=model_id,
            config=types.GetModelConfig(http_options=http_options(10_000)),
        )
        return result.name

    async def count(self, model_id: str, text: str) -> int | None:
        """Count text-only prompt tokens; do not use heuristic counts as telemetry."""
        result = await self.client.models.count_tokens(
            model=model_id,
            contents=text,
            config=types.CountTokensConfig(http_options=http_options(10_000)),
        )
        return result.total_tokens

    async def generate(self, model_id: str, text: str) -> Generation:
        """Make exactly one SDK generation invocation and preserve original text."""
        started = time.monotonic()
        response = await self.client.models.generate_content(
            model=model_id, contents=text, config=generation_config()
        )
        elapsed = time.monotonic() - started
        candidates = response.candidates or []
        candidate = candidates[0] if len(candidates) == 1 else None
        body = candidate.content if candidate else None
        parts = body.parts if body else None
        text_parts = [
            part.text
            for part in (parts or [])
            if part.text is not None and not part.thought
        ]
        metadata = response.usage_metadata
        usage = (
            Usage()
            if metadata is None
            else Usage(
                input_tokens=metadata.prompt_token_count,
                candidate_tokens=metadata.candidates_token_count,
                thinking_tokens=metadata.thoughts_token_count,
                cached_tokens=metadata.cached_content_token_count,
                total_tokens=metadata.total_token_count,
                tool_tokens=metadata.tool_use_prompt_token_count,
            )
        )
        return Generation(
            text="".join(text_parts),
            model_version=response.model_version,
            finish_reason=(
                candidate.finish_reason.value
                if candidate and candidate.finish_reason
                else None
            ),
            usage=usage,
            elapsed_seconds=elapsed,
        )


class Ledger:
    """Reserve once before any RPC; every dispatched operation consumes its slot."""

    def __init__(self, directory: Path, plan: Plan) -> None:
        """Refuse replay even after a timeout or interrupted/failed run."""
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f"{plan.plan_sha256}.json"
        self.limits = {
            "metadata": 2,
            "count": len(plan.requests),
            "generate": len(plan.requests),
        }
        self.data: dict[str, object] = {
            "plan_sha256": plan.plan_sha256,
            "benchmark_sha256": plan.benchmark_sha256,
            "created_at": datetime.now(UTC).isoformat(),
            "status": "reserved",
            "operations": [],
            "generations": [],
            "total_catalog_cost_usd": str(plan.prior_catalog_cost_usd),
            "known_catalog_cost_usd": str(plan.prior_catalog_cost_usd),
            "prior_catalog_cost_usd": str(plan.prior_catalog_cost_usd),
            "prior_ledger_sha256": plan.prior_ledger_sha256,
            "usage_policy": plan.usage_policy,
            "billing_status": "no new generation dispatched; prior estimate included if present",
            "carbon": "uncalibrated; no provider energy measurement",
        }
        try:
            descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as error:
            raise RunError(
                "Plan already reserved/consumed; refusing automatic replay"
            ) from error
        with os.fdopen(descriptor, "w") as handle:
            json.dump(self.data, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())

    def save(self) -> None:
        """Atomically persist state before sending and after receiving each request."""
        temporary = self.path.with_suffix(".writing")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            json.dump(self.data, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(self.path)

    def dispatch(
        self, kind: str, model_id: str, task: str | None = None
    ) -> dict[str, object]:
        """Reserve a bounded HTTP slot before making any external request."""
        operations = cast(list[dict[str, object]], self.data["operations"])
        limit = self.limits[kind]
        if sum(operation["kind"] == kind for operation in operations) >= limit:
            raise RunError("Approved operation count exhausted")
        operation: dict[str, object] = {
            "kind": kind,
            "model_id": model_id,
            "task_id": task,
            "status": "dispatched",
        }
        operations.append(operation)
        self.save()
        return operation


async def execute(
    plan: Plan,
    provider: Provider,
    ledger: Ledger,
    evaluate: Callable[[Exercise, str], dict[str, object]],
) -> dict[str, object]:
    """Run serially; any uncertain billing/access/configuration stops later calls."""
    generations = cast(list[dict[str, object]], ledger.data["generations"])
    versions: dict[str, str] = {}
    total = plan.prior_catalog_cost_usd
    try:
        for rate in plan.models.values():
            operation = ledger.dispatch("metadata", rate.id)
            name = await provider.model(rate.id)
            if not name or not name.endswith(rate.id):
                raise RunError("Model metadata missing or mismatched")
            operation.update(status="completed", name=name)
            ledger.save()
        for spec in plan.requests:
            text = prompt(EXERCISES[spec.task_id])
            operation = ledger.dispatch("count", spec.model_id, spec.task_id)
            tokens = await provider.count(spec.model_id, text)
            if tokens is None or tokens < 1 or tokens > 4096:
                raise RunError("Prompt count missing or above approved limit")
            operation.update(status="completed", tokens=tokens)
            ledger.save()
            rate = plan.models[spec.model_role]
            reserve = (
                Decimal(4096) * rate.input_usd_per_million
                + Decimal(8192) * rate.generated_usd_per_million
            ) / Decimal(1_000_000)
            if total + reserve > Decimal("0.50"):
                raise RunError("Insufficient approved remaining allowance")
            operation = ledger.dispatch("generate", spec.model_id, spec.task_id)
            ledger.data["total_catalog_cost_usd"] = None
            ledger.data["billing_status"] = "uncertain until validated usage returns"
            ledger.save()
            result = await provider.generate(spec.model_id, text)
            record: dict[str, object] = {
                "task_id": spec.task_id,
                "model_role": spec.model_role,
                "model_id": spec.model_id,
                "model_version": result.model_version,
                "prompt_sha256": spec.prompt_sha256,
                "raw_text": result.text,
                "finish_reason": result.finish_reason,
                "elapsed_seconds": result.elapsed_seconds,
                "usage": result.usage.model_dump(),
                "quality": None,
                "catalog_cost_usd": None,
            }
            generations.append(record)
            operation.update(status="response_received")
            ledger.save()
            inputs, outputs = result.usage.checked(plan.usage_policy)
            record["usage_interpretation"] = {
                "policy": plan.usage_policy,
                "effective": result.usage.effective(plan.usage_policy).model_dump(),
                "raw_usage_preserved": True,
            }
            if not result.model_version or not result.model_version.startswith(
                spec.model_id
            ):
                raise RunError("Response model version missing or mismatched")
            if (
                spec.model_id in versions
                and result.model_version != versions[spec.model_id]
            ):
                raise RunError("Model version changed during run")
            versions[spec.model_id] = result.model_version
            cost = (
                Decimal(inputs) * rate.input_usd_per_million
                + Decimal(outputs) * rate.generated_usd_per_million
            ) / Decimal(1_000_000)
            total += cost
            record["catalog_cost_usd"] = str(cost)
            ledger.data["total_catalog_cost_usd"] = str(total)
            ledger.data["known_catalog_cost_usd"] = str(total)
            ledger.data["billing_status"] = (
                "catalog estimate before credits/tax/FX; all dispatched generations accounted for"
            )
            ledger.save()
            if total > Decimal("0.50"):
                raise RunError("Observed run allowance exceeded")
            if result.finish_reason != "STOP" or not result.text.strip():
                record["quality"] = {
                    "accepted": False,
                    "reason": "Incomplete or non-STOP candidate",
                }
            else:
                try:
                    validate_suite(result.text)
                except SandboxError as error:
                    record["quality"] = {"accepted": False, "reason": str(error)}
                else:
                    try:
                        record["quality"] = await asyncio.to_thread(
                            evaluate, EXERCISES[spec.task_id], result.text
                        )
                    except SandboxError as error:
                        record["quality"] = {"accepted": False, "reason": str(error)}
                        raise RunError(
                            "Sandbox infrastructure failed; no further generation"
                        ) from error
            operation.update(status="completed")
            ledger.save()
        ledger.data["status"] = "completed"
        ledger.data["policy_replay"] = policy_replay(generations)
    except Exception as error:
        ledger.data["status"] = "stopped"
        # Provider errors can contain request data; persist only the type, unless ours.
        ledger.data["stop_reason"] = (
            str(error)
            if isinstance(error, RunError)
            else f"{type(error).__name__}; uncertain request outcome; no retry"
        )
    finally:
        ledger.save()
    return ledger.data


def policy_replay(generations: list[dict[str, object]]) -> list[dict[str, object]]:
    """Pair completed candidates; count compact failures in replayed routing cost."""
    rows: list[dict[str, object]] = []
    for task in ("clamp", "discount", "merge"):
        pair = {
            str(item["model_role"]): item
            for item in generations
            if item["task_id"] == task
        }
        if set(pair) != {"compact", "strong"}:
            continue
        compact, strong = pair["compact"], pair["strong"]
        compact_ok = cast(dict[str, object], compact["quality"])["accepted"] is True
        strong_ok = cast(dict[str, object], strong["quality"])["accepted"] is True
        selected = [compact] if compact_ok else [compact, strong]
        rows.append(
            {
                "task_id": task,
                "baseline_accepted": strong_ok,
                "compact_first_accepted": compact_ok or strong_ok,
                "escalated": not compact_ok,
                "baseline_catalog_cost_usd": strong["catalog_cost_usd"],
                "compact_first_catalog_cost_usd": str(
                    sum(Decimal(str(item["catalog_cost_usd"])) for item in selected)
                ),
                "efficiency_comparison_supported": strong_ok
                and (compact_ok or strong_ok),
                "provenance": "paired policy replay from independently generated suites",
                "carbon": "unavailable; provider energy uncalibrated",
            }
        )
    return rows


def user_adc(plan: Plan) -> Credentials:
    """Load only the approved local user ADC; never fall back to an ambient key."""
    path = Path.home() / ".config/gcloud/application_default_credentials.json"
    if not path.is_file():
        raise RunError("Complete Google sign-in before live execution")
    load = cast(Callable[[str], Credentials], Credentials.from_authorized_user_file)
    credentials = load(str(path))
    if credentials.quota_project_id != plan.project:
        raise RunError(
            "Set the ADC quota project to carbontrace-511814 before execution"
        )
    return credentials


def check_prior_evidence(plan: Plan, directory: Path) -> None:
    """Bind reuse of the first response to immutable evidence and its token cost."""
    if plan.usage_policy != "protojson_v2":
        if plan.prior_catalog_cost_usd or plan.prior_ledger_sha256:
            raise RunError("Strict original plans cannot import prior evidence")
        return
    path = directory / f"{REPLACEMENT_HASH}.json"
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != plan.prior_ledger_sha256:
        raise RunError("Prior response ledger differs from the reviewed continuation")
    source = json.loads(content)
    rows = source.get("generations", [])
    if source.get("status") != "stopped" or len(rows) != 1:
        raise RunError("Expected exactly one saved response from the stopped attempt")
    row = rows[0]
    rate = plan.models["compact"]
    if (
        row.get("task_id") != "clamp"
        or row.get("model_role") != "compact"
        or row.get("model_id") != rate.id
        or row.get("model_version") != rate.id
        or row.get("finish_reason") != "STOP"
        or row.get("prompt_sha256")
        != hashlib.sha256(prompt(EXERCISES["clamp"]).encode()).hexdigest()
    ):
        raise RunError("Prior response cannot be reused for this comparison")
    inputs, outputs = Usage.model_validate(row["usage"]).checked("protojson_v2")
    cost = (
        Decimal(inputs) * rate.input_usd_per_million
        + Decimal(outputs) * rate.generated_usd_per_million
    ) / Decimal(1_000_000)
    if cost != plan.prior_catalog_cost_usd:
        raise RunError("Prior response estimate differs from the approved allowance")


async def run_live(plan: Plan, directory: Path, image: str) -> dict[str, object]:
    """Create a real provider only after explicit CLI approval and sandbox checks."""
    check_prior_evidence(plan, directory)
    runner = ContainerRunner(image, Path(".tmp/sandbox"))
    runner.preflight()
    credentials = user_adc(plan)
    ledger = Ledger(directory, plan)
    try:
        async with genai.Client(
            enterprise=True,
            project=plan.project,
            location=plan.location,
            credentials=credentials,
            http_options=client_http_options(),
        ).aio as client:
            return await execute(plan, GeminiProvider(client), ledger, runner.evaluate)
    except Exception as error:
        ledger.data.update(
            status="stopped",
            stop_reason=f"{type(error).__name__}; client setup failed; no retry",
        )
        ledger.save()
        return ledger.data


def main(argv: list[str] | None = None) -> None:
    """Explicit live CLI; no web route, startup hook, or environment-based unlock."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--execute-approved-smoke", action="store_true", required=True)
    args = parser.parse_args(argv)
    try:
        plan = load_approved_plan(args.plan, args.approval)
        result = asyncio.run(run_live(plan, Path("data/live-ledgers"), args.image))
    except (OSError, ValueError, RunError, SandboxError) as error:
        parser.error(str(error))
    print(
        f"Smoke status: {result['status']}. Evidence: data/live-ledgers/{plan.plan_sha256}.json"
    )
    if result["status"] != "completed":
        raise SystemExit(1)


if __name__ == "__main__":  # pragma: no cover
    main()
