"""Signed one-request plans and a durable, fail-closed public execution pool."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol
from uuid import uuid4

from pydantic import Field, StrictBool

from carbontrace.decision import MODELS
from carbontrace.domain import Contract
from carbontrace.live_comparison import RATES, digest, prepare_selected_quote
from carbontrace.live_smoke import Provider, RunError
from carbontrace.preflight import PreflightRequest

POOL_LIMIT = 6
POOL_EPOCH = "carbontrace-public-demo-20261018-v1"


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


class HostedApproval(Contract):
    plan: SignedQuote
    approval_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    allowance_usd: Decimal = Field(ge=0, le=Decimal("0.10"))
    agreed: StrictBool


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def make_quote(
    draft: PreflightRequest, run_id: str, created: datetime, settings: HostedSettings
) -> dict[str, Any]:
    quote = prepare_selected_quote(draft, run_id, created)
    quote.pop("plan_sha256")
    quote.update(
        schema_version=3,
        execution_mode="hosted_selected_model",
        expires_at=min(
            created + timedelta(minutes=10), settings.expires_at
        ).isoformat(),
        pool_epoch=POOL_EPOCH,
        pool_limit=POOL_LIMIT,
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
    draft: PreflightRequest, settings: HostedSettings, now: datetime | None = None
) -> SignedQuote:
    now = now or datetime.now(UTC)
    if now >= settings.expires_at:
        raise PoolExhausted(
            "The public run period has ended. Planning and recorded results remain available."
        )
    quote = make_quote(draft, uuid4().hex, now, settings)
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
            PreflightRequest.model_validate(quote["draft"]), run_id, created, settings
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
    """A fixed epoch survives revisions; no failed reservation is refunded."""

    def __init__(self, objects: Objects):
        self.objects = objects

    def meter(self) -> tuple[dict[str, Any], int]:
        found = self.objects.read(f"budget/{POOL_EPOCH}.json")
        if found is None:
            raise HostedError(
                "Public allowance is not initialized; execution is stopped"
            )
        value, generation = found
        if (
            value.get("epoch") != POOL_EPOCH
            or value.get("limit") != POOL_LIMIT
            or not isinstance(value.get("runs"), dict)
            or len(value["runs"]) > POOL_LIMIT
        ):
            raise HostedError("Public allowance could not be verified")
        return value, generation

    def remaining(self) -> int:
        return POOL_LIMIT - len(self.meter()[0]["runs"])

    def reserve(self, quote: dict[str, Any]) -> bool:
        for _ in range(6):
            meter, generation = self.meter()
            prior = meter["runs"].get(quote["id"])
            if prior:
                if prior["plan_sha256"] != quote["plan_sha256"]:
                    raise HostedError("Reservation mismatch")
                return False
            if len(meter["runs"]) >= POOL_LIMIT:
                raise PoolExhausted(
                    "The shared six-run allowance is exhausted. Planning and recorded results remain available."
                )
            meter["runs"][quote["id"]] = {
                "plan_sha256": quote["plan_sha256"],
                "model_id": quote["models"][0]["model_id"],
                "reserved_at": datetime.now(UTC).isoformat(),
            }
            try:
                self.objects.write(f"budget/{POOL_EPOCH}.json", meter, generation)
                return True
            except Conflict:
                continue
        raise HostedError("Public allowance is busy; no generation was sent")

    def save(self, state: dict[str, Any]) -> None:
        self.objects.write(f"runs/{POOL_EPOCH}/{state['id']}.json", state)

    def receipt(self, run_id: str) -> dict[str, Any] | None:
        if not re.fullmatch(r"[0-9a-f]{32}", run_id):
            raise HostedError("Invalid run ID")
        found = self.objects.read(f"runs/{POOL_EPOCH}/{run_id}.json")
        return found[0] if found else None


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
    # Storage must succeed before client creation or either provider operation.
    await asyncio.to_thread(ledger.save, state)
    try:
        async with provider_factory() as provider:
            model = quote["models"][0]["model_id"]
            state["operations"].append("count_tokens_dispatched")
            await asyncio.to_thread(ledger.save, state)
            count = await provider.count(model, quote["exact_payload"])
            if count is None or not 0 < count <= 4096:
                raise RunError(
                    "Input token count is missing or exceeds 4096; generation was not sent"
                )
            state["input_token_count"] = count
            state["operations"].append("generate_dispatched")
            state["billing_uncertain"] = True
            await asyncio.to_thread(ledger.save, state)
            generation = await provider.generate(model, quote["exact_payload"])
            state["response"] = {
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
                raise RunError(
                    "Returned model version does not match the approved model"
                )
            rates = RATES[MODELS.index(model)]
            state["response"].update(
                effective_usage=generation.usage.effective(
                    "protojson_full_v3"
                ).model_dump(mode="json"),
                estimated_cost_usd=str(
                    (inputs * rates[0] + generated * rates[1]) / 1_000_000
                ),
                complete_output=generation.finish_reason == "STOP"
                and bool(generation.text),
            )
            state.update(status="completed", billing_uncertain=False)
    except asyncio.CancelledError:
        state["status"] = "interrupted"
        await asyncio.to_thread(ledger.save, state)
        raise
    except Exception as exc:
        state.update(
            status="failed",
            error=(
                str(exc)
                if isinstance(exc, RunError)
                else "Execution stopped; the reservation remains consumed. No automatic retry."
            ),
        )
    state["finished_at"] = datetime.now(UTC).isoformat()
    try:
        await asyncio.to_thread(ledger.save, state)
    except HostedError:
        state["persistence_warning"] = (
            "Final receipt could not be saved. This reservation cannot be executed again."
        )
    return state
