"""Signed one-request plans and a durable, fail-closed public execution pool."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from typing import Any, Protocol
from uuid import uuid4

from pydantic import Field, StrictBool

from carbontrace.decision import MODELS
from carbontrace.domain import Contract
from carbontrace.live_comparison import RATES, digest, prepare_selected_quote
from carbontrace.live_smoke import Provider, RunError
from carbontrace.preflight import PreflightRequest

MODEL_BUDGET_MICROUSD = 4_000_000
POOL_EPOCH = "carbontrace-public-demo-20261018-v1"


def reservation_microusd(model: str) -> int:
    """Reserve the full-rate stress scenario, rounded upward to a microdollar."""
    rates = RATES[MODELS.index(model)]
    return int((4096 * rates[0] + 8192 * rates[1]).to_integral_value(ROUND_CEILING))


class HostedError(RuntimeError):
    """A public, sanitized execution failure."""


class Conflict(HostedError):
    """An atomic storage precondition failed."""


class PoolExhausted(HostedError):
    """All globally shared reservations have been consumed."""


class Objects(Protocol):
    """Object writes must enforce the supplied generation, including create-only 0."""

    def read(self, name: str) -> tuple[dict[str, Any], int] | None: ...
    def write(
        self, name: str, value: dict[str, Any], generation: int | None = None
    ) -> None: ...


@dataclass(frozen=True)
class HostedSettings:
    signing_key: bytes
    expires_at: datetime

    def __post_init__(self) -> None:
        if len(self.signing_key) < 32 or self.expires_at.tzinfo is None:
            raise HostedError("Hosted execution configuration is unavailable")


class SignedQuote(Contract):
    quote: dict[str, Any]
    signature: str = Field(pattern=r"^[0-9a-f]{64}$")


class HostedDraft(PreflightRequest):
    compare_models: StrictBool = False


class HostedApproval(Contract):
    plan: SignedQuote
    approval_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    allowance_usd: Decimal = Field(ge=0, le=Decimal("0.10"))
    agreed: StrictBool


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def make_quote(
    draft: PreflightRequest,
    run_id: str,
    created: datetime,
    settings: HostedSettings,
    compare_models: bool = False,
) -> dict[str, Any]:
    quote = prepare_selected_quote(draft, run_id, created)
    quote.pop("plan_sha256")
    models = quote["models"]
    assert isinstance(models, list)
    if compare_models:
        models = []
        estimates, stresses = Decimal(0), Decimal(0)
        for role in ("compact", "strong"):
            part = prepare_selected_quote(
                draft.model_copy(update={"selected_model": role}), run_id, created
            )
            assert part["exact_payload"] == quote["exact_payload"]
            entries = part["models"]
            assert isinstance(entries, list)
            models.extend(entries)
            estimates += Decimal(str(part["estimated_cost_usd"]))
            stresses += Decimal(str(part["stress_cost_usd"]))
        quote.update(
            models=models,
            estimated_cost_usd=str(estimates),
            stress_cost_usd=str(stresses),
            generation_calls=2,
            token_count_calls=2,
        )
    reserved_usd = str(
        Decimal(sum(reservation_microusd(m["model_id"]) for m in models)) / 1_000_000
    )
    quote.update(
        schema_version=5,
        execution_mode=(
            "hosted_model_comparison" if compare_models else "hosted_selected_model"
        ),
        expires_at=min(
            created + timedelta(minutes=10), settings.expires_at
        ).isoformat(),
        pool_epoch=POOL_EPOCH,
        pool_budget_usd=str(Decimal(MODEL_BUDGET_MICROUSD) / 1_000_000),
        reservation_usd=reserved_usd,
        allowance_usd=reserved_usd,
        pool_expires_at=settings.expires_at.isoformat(),
        metadata_reads=0,
        quality_task=None,
        quality_note="Fresh output is text only; quality has not been evaluated.",
        privacy_note="Approved request and response are stored privately and scheduled for deletion after seven days. Do not submit secrets.",
        pricing_checked="2026-10-18",
    )
    quote["plan_sha256"] = digest(quote)
    return quote


def issue_quote(
    draft: PreflightRequest,
    settings: HostedSettings,
    now: datetime | None = None,
    *,
    compare_models: bool = False,
) -> SignedQuote:
    now = now or datetime.now(UTC)
    if now >= settings.expires_at:
        raise PoolExhausted(
            "The public run period has ended. Planning and recorded results remain available."
        )
    quote = make_quote(draft, uuid4().hex, now, settings, compare_models)
    return SignedQuote(
        quote=quote,
        signature=hmac.new(
            settings.signing_key, canonical(quote), hashlib.sha256
        ).hexdigest(),
    )


def check_approval(
    approval: HostedApproval, settings: HostedSettings, now: datetime | None = None
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    quote = approval.plan.quote
    expected = hmac.new(
        settings.signing_key, canonical(quote), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, approval.plan.signature):
        raise HostedError("The approved quote was changed")
    try:
        run_id = quote["id"]
        created = datetime.fromisoformat(quote["created_at"])
        if not re.fullmatch(r"[0-9a-f]{32}", run_id) or created.tzinfo is None:
            raise ValueError
        rebuilt = make_quote(
            PreflightRequest.model_validate(quote["draft"]),
            run_id,
            created,
            settings,
            quote["execution_mode"] == "hosted_model_comparison",
        )
        if rebuilt != quote:
            raise ValueError
        expired = now >= datetime.fromisoformat(
            quote["expires_at"]
        ) or now < created - timedelta(seconds=10)
    except (ValueError, TypeError, KeyError) as exc:
        raise HostedError("Invalid approved plan") from exc
    if expired:
        raise HostedError(
            "Quote expired; prepare a new quote without sending a generation"
        )
    if (
        not approval.agreed
        or approval.approval_hash != quote["plan_sha256"]
        or approval.allowance_usd != Decimal(quote["allowance_usd"])
    ):
        raise HostedError("Explicit approval of this exact priced request is required")
    return quote


class HostedLedger:
    """A fixed dollar allowance survives revisions; reservations are not refunded."""

    def __init__(self, objects: Objects):
        self.objects = objects

    def meter(self) -> tuple[dict[str, Any], int]:
        found = self.objects.read(f"budget/{POOL_EPOCH}.json")
        if found is None:
            raise HostedError(
                "Public allowance is not initialized; execution is stopped"
            )
        value, generation = found
        if value.get("epoch") != POOL_EPOCH or not isinstance(value.get("runs"), dict):
            raise HostedError("Public allowance could not be verified")
        # Convert the original six-run ledger without changing its epoch or IDs.
        # Persist only under CAS on the next reservation. Old revisions reject
        # the migrated format because it deliberately has no six-run limit field.
        legacy = value.get("schema_version") is None and value.get("limit") == 6
        if legacy:
            if len(value["runs"]) > 6:
                raise HostedError("Public allowance could not be verified")
            value.pop("limit")
            value.update(schema_version=2, budget_microusd=MODEL_BUDGET_MICROUSD)
        elif (
            value.get("schema_version") != 2
            or value.get("budget_microusd") != MODEL_BUDGET_MICROUSD
            or "limit" in value
        ):
            raise HostedError("Public allowance could not be verified")
        for run_id, row in value["runs"].items():
            try:
                if (
                    not re.fullmatch(r"[0-9a-f]{32}", run_id)
                    or not isinstance(row, dict)
                    or not re.fullmatch(r"[0-9a-f]{64}", row["plan_sha256"])
                ):
                    raise ValueError
                model_ids = row.get("model_ids", [row["model_id"]])
                if (
                    model_ids not in ([MODELS[0]], [MODELS[1]], list(MODELS))
                    or row["model_id"] != model_ids[0]
                ):
                    raise ValueError
                amount = sum(reservation_microusd(model) for model in model_ids)
                if legacy:
                    row["reserved_microusd"] = amount
                if (
                    type(row["reserved_microusd"]) is not int
                    or row["reserved_microusd"] != amount
                ):
                    raise ValueError
            except (ValueError, TypeError, KeyError) as exc:
                raise HostedError("Public allowance could not be verified") from exc
        if self.used(value) > MODEL_BUDGET_MICROUSD:
            raise HostedError("Public allowance could not be verified")
        return value, generation

    @staticmethod
    def used(meter: dict[str, Any]) -> int:
        return sum(row["reserved_microusd"] for row in meter["runs"].values())

    def status(self) -> dict[str, object]:
        meter = self.meter()[0]
        return {
            "budget_usd": str(Decimal(MODEL_BUDGET_MICROUSD) / 1_000_000),
            "reserved_usd": str(Decimal(self.used(meter)) / 1_000_000),
            "remaining_usd": str(
                Decimal(MODEL_BUDGET_MICROUSD - self.used(meter)) / 1_000_000
            ),
            "runs_reserved": len(meter["runs"]),
            "generations_reserved": sum(
                len(row.get("model_ids", [row["model_id"]]))
                for row in meter["runs"].values()
            ),
            "halted": bool(meter.get("halted")),
        }

    def reserve(self, quote: dict[str, Any]) -> bool:
        for _ in range(6):
            meter, generation = self.meter()
            prior = meter["runs"].get(quote["id"])
            if prior:
                if prior["plan_sha256"] != quote["plan_sha256"]:
                    raise HostedError("Reservation mismatch")
                return False
            model_ids = [model["model_id"] for model in quote["models"]]
            amount = sum(reservation_microusd(model) for model in model_ids)
            if meter.get("halted") or self.used(meter) + amount > MODEL_BUDGET_MICROUSD:
                raise PoolExhausted(
                    "The shared demo budget cannot fund this request. Planning and recorded results remain available."
                )
            meter["runs"][quote["id"]] = {
                "plan_sha256": quote["plan_sha256"],
                "model_id": model_ids[0],
                "model_ids": model_ids,
                "reserved_microusd": amount,
                "reserved_at": datetime.now(UTC).isoformat(),
            }
            try:
                self.objects.write(f"budget/{POOL_EPOCH}.json", meter, generation)
                return True
            except Conflict:
                continue
        raise HostedError("Public allowance is busy; no generation was sent")

    def halt(self) -> None:
        """Stop fresh dispatch if a returned cost exceeds its stress reservation."""
        for _ in range(6):
            meter, generation = self.meter()
            meter["halted"] = True
            try:
                self.objects.write(f"budget/{POOL_EPOCH}.json", meter, generation)
                return
            except Conflict:
                continue
        raise HostedError("Could not persist the budget stop; operator review required")

    def save(self, state: dict[str, Any]) -> None:
        self.objects.write(f"runs/{POOL_EPOCH}/{state['id']}.json", state)

    def receipt(self, run_id: str) -> dict[str, Any] | None:
        if not re.fullmatch(r"[0-9a-f]{32}", run_id):
            raise HostedError("Invalid run ID")
        found = self.objects.read(f"runs/{POOL_EPOCH}/{run_id}.json")
        return found[0] if found else None


async def dispatch_model(
    model: str,
    payload: str,
    record: dict[str, Any],
    provider: Provider,
    persist: Callable[[], Awaitable[None]],
) -> None:
    """Dispatch one already-reserved model; the caller persists the parent receipt."""
    record["operations"].append("count_tokens_dispatched")
    await persist()
    count = await provider.count(model, payload)
    if count is None or not 0 < count <= 4096:
        raise RunError(
            "Input token count is missing or exceeds 4096; generation was not sent"
        )
    record["input_token_count"] = count
    record["operations"].append("generate_dispatched")
    record["billing_uncertain"] = True
    await persist()
    generation = await provider.generate(model, payload)
    record["response"] = {
        "text": generation.text,
        "model_version": generation.model_version,
        "finish_reason": generation.finish_reason,
        "raw_usage": generation.usage.model_dump(mode="json"),
        "elapsed_seconds": generation.elapsed_seconds,
        "quality": "not_evaluated",
    }
    inputs, generated = generation.usage.checked("protojson_full_v3")
    if generation.usage.effective("protojson_full_v3").cached_tokens != 0:
        raise RunError("Unexpected cache usage; cost needs review")
    if generation.model_version != model and not (
        generation.model_version or ""
    ).startswith(model + "-"):
        raise RunError("Returned model version does not match the approved model")
    rates = RATES[MODELS.index(model)]
    record["response"].update(
        effective_usage=generation.usage.effective("protojson_full_v3").model_dump(
            mode="json"
        ),
        estimated_cost_usd=str((inputs * rates[0] + generated * rates[1]) / 1_000_000),
        complete_output=generation.finish_reason == "STOP" and bool(generation.text),
    )
    if (inputs * rates[0] + generated * rates[1]) > reservation_microusd(model):
        raise RunError(
            "Usage exceeded the reserved estimate; fresh runs stopped for review"
        )
    record.update(
        status="completed",
        billing_uncertain=False,
        finished_at=datetime.now(UTC).isoformat(),
    )
    await persist()


def comparison_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Observed costs are comparable; quality and actual carbon are not inferred."""
    complete = all(
        row["status"] == "completed" and row["response"]["complete_output"]
        for row in records
    )
    summary: dict[str, Any] = {
        "complete": complete,
        "quality": "not_evaluated",
        "recommended_model_id": None,
        "note": "Review both outputs against your requirements. Cost and token usage alone do not establish equal quality or lower carbon.",
        "latency_note": "One sequential observation per model, not a controlled latency benchmark.",
    }
    if complete:
        costs = {
            row["model_id"]: Decimal(row["response"]["estimated_cost_usd"])
            for row in records
        }
        low, high = min(costs.values()), max(costs.values())
        summary.update(
            lower_observed_cost_model=(
                min(costs, key=lambda model: costs[model]) if low != high else None
            ),
            cost_difference_usd=str(high - low),
            combined_cost_usd=str(sum(costs.values())),
            cost_reduction_percent=str((high - low) / high * 100) if high else "0",
        )
    return summary


async def execute_hosted(
    quote: dict[str, Any],
    ledger: HostedLedger,
    provider_factory: Callable[[], AbstractAsyncContextManager[Provider]],
) -> dict[str, Any]:
    if not await asyncio.to_thread(ledger.reserve, quote):
        return await asyncio.to_thread(ledger.receipt, quote["id"]) or {
            "id": quote["id"],
            "status": "reserved",
            "note": "Already reserved. This request will never be dispatched again.",
        }
    state: dict[str, Any] = {
        "id": quote["id"],
        "status": "reserved",
        "quote": quote,
        "started_at": datetime.now(UTC).isoformat(),
        "operations": [],
        "response": None,
        "billing_uncertain": False,
        "actual_energy_wh": None,
        "actual_carbon_g": None,
    }
    paired = len(quote["models"]) == 2
    records = (
        [
            {
                "model_id": model["model_id"],
                "model_name": model["model_name"],
                "status": "not_started",
                "operations": [],
                "response": None,
                "billing_uncertain": False,
            }
            for model in quote["models"]
        ]
        if paired
        else [state]
    )
    if paired:
        state["responses"] = records
    active = records[0]

    async def persist() -> None:
        if paired:
            state["billing_uncertain"] = any(
                row["billing_uncertain"] for row in records
            )
        await asyncio.to_thread(ledger.save, state)

    # Storage must succeed before client creation or either provider operation.
    await asyncio.to_thread(ledger.save, state)
    try:
        async with provider_factory() as provider:
            for entry, active in zip(quote["models"], records, strict=True):
                await dispatch_model(
                    entry["model_id"], quote["exact_payload"], active, provider, persist
                )
            state.update(status="completed", billing_uncertain=False)
    except asyncio.CancelledError:
        state["status"] = "interrupted"
        active["status"] = "interrupted"
        await asyncio.to_thread(ledger.save, state)
        raise
    except Exception as exc:
        if isinstance(exc, RunError) and "generate_dispatched" in active["operations"]:
            try:
                await asyncio.to_thread(ledger.halt)
            except HostedError:
                state["budget_stop_warning"] = (
                    "Budget stop could not be persisted; operator review required"
                )
        state.update(
            status=(
                "partial_failure"
                if paired and any(row["status"] == "completed" for row in records)
                else "failed"
            ),
            error=(
                str(exc)
                if isinstance(exc, RunError)
                else "Execution stopped; the reservation remains consumed. No automatic retry."
            ),
        )
        if paired:
            active.update(status="failed", error=state["error"])
            state["billing_uncertain"] = any(
                row["billing_uncertain"] for row in records
            )
    if paired:
        state["comparison"] = comparison_summary(records)
    state["finished_at"] = datetime.now(UTC).isoformat()
    try:
        await asyncio.to_thread(ledger.save, state)
    except HostedError:
        state["persistence_warning"] = (
            "Final receipt could not be saved. This reservation cannot be executed again."
        )
    return state
