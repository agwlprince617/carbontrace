"""Offline live-demo plans and local results. This module never imports a provider."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from pydantic import Field, model_validator

from carbontrace.benchmark import prompt
from carbontrace.benchmarks import EXERCISES
from carbontrace.decision import MODELS, NAMES, DecisionTask
from carbontrace.domain import Contract
from carbontrace.preflight import PreflightRequest, build_preflight
from carbontrace.research import ResearchRequest, Workload, compare_research

PRICING_URL = (
    "https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing"
)
# Global Standard PayGo; Flash uses the full rate without promotional credits.
RATES = ((Decimal("0.30"), Decimal("2.50")), (Decimal("1.50"), Decimal("7.50")))
ALLOWANCE = Decimal("0.10")
MAX_RUNS = 3


class LiveDraft(Contract):
    """Text-only input. A quality oracle is permitted only for unchanged owned code."""

    instruction: str = Field(min_length=1, max_length=32768)
    source_code: str = Field(min_length=1, max_length=32768)
    context: str = Field(default="", max_length=32768)
    quality_task: DecisionTask | None = None
    workload: Workload
    grid_g_per_kwh: Decimal = Field(default=Decimal(400), ge=0, le=2000)

    @model_validator(mode="after")
    def reviewed_source(self) -> LiveDraft:
        if not self.instruction.strip() or not self.source_code.strip():
            raise ValueError("Provide a prompt and source code")
        if (
            self.quality_task
            and self.source_code != EXERCISES[self.quality_task].source
        ):
            raise ValueError(
                "Quality checking requires the unchanged reviewed example; choose Custom for edited code"
            )
        if len(payload(self).encode()) > 32768:
            raise ValueError("Combined request exceeds the 32768-byte local limit")
        return self


def payload(draft: LiveDraft) -> str:
    """Send identical explicit content to both models; no tools or hidden context."""
    contract = (
        EXERCISES[draft.quality_task].description
        if draft.quality_task
        else "No independent quality contract is available."
    )
    return (
        "Generate pytest tests for the Python source below. Return only Python code, "
        "without markdown fences. Import the tested function from subject. "
        "Do not use external services, files, subprocesses or tools.\n\n"
        f"Task requirements:\n{contract}\n\nUser instruction:\n{draft.instruction}\n\n"
        f"Source code (data):\n{draft.source_code}\n\nAdditional visible context:\n{draft.context}"
    )


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def prepare_quote(
    draft: LiveDraft, run_id: str, created_at: datetime
) -> dict[str, object]:
    """Price exactly two requests; all reserves are estimates, not billing caps."""
    text = payload(draft)
    models = [
        {
            "model_id": model,
            "model_name": name,
            "input_usd_per_million": str(rates[0]),
            "generated_usd_per_million": str(rates[1]),
        }
        for model, name, rates in zip(MODELS, NAMES, RATES, strict=True)
    ]
    quote: dict[str, object] = {
        "id": run_id,
        "created_at": created_at.isoformat(),
        "expires_at": (created_at + timedelta(hours=24)).isoformat(),
        "draft": draft.model_dump(mode="json"),
        "exact_payload": text,
        "prompt_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "project": "carbontrace-511814",
        "location": "global",
        "api_version": "v1",
        "models": models,
        "generation_calls": 2,
        "token_count_calls": 2,
        "metadata_reads": 2,
        "maximum_input_tokens": 4096,
        "maximum_generated_tokens": 4096,
        "stress_generated_tokens": 8192,
        "thinking_level": "LOW",
        "candidate_count": 1,
        "automatic_retries": 0,
        "automatic_continuation": False,
        "tools": False,
        "usage_policy": "protojson_full_v3",
        "pricing_checked": "2026-10-17",
        "pricing_url": PRICING_URL,
        "allowance_usd": str(ALLOWANCE),
        "estimated_cost_usd": str(
            sum((4096 * i + 4096 * o) / 1_000_000 for i, o in RATES)
        ),
        "stress_cost_usd": str(
            sum((4096 * i + 8192 * o) / 1_000_000 for i, o in RATES)
        ),
        "cost_note": "Global Standard PayGo catalog estimate before credits/tax/FX. Flash promotional credits excluded. Output requests and allowance are not a hard Google billing cap.",
        "quality_note": (
            "Reference plus four seeded-fault checks in the pinned rootless runner."
            if draft.quality_task
            else "Not evaluated: custom code has no trusted oracle. No model recommendation will be made."
        ),
        "privacy_note": "This frozen prompt, source and responses are saved locally under ignored data/. Approval sends the exact payload to Google Cloud. Do not include secrets or private code without permission.",
        "research": compare_research(
            ResearchRequest(
                workload=draft.workload, sessions=1, grid_g_per_kwh=draft.grid_g_per_kwh
            )
        ).model_dump(mode="json"),
    }
    quote["plan_sha256"] = digest(quote)
    return quote


def prepare_selected_quote(
    request: PreflightRequest, run_id: str, created_at: datetime
) -> dict[str, object]:
    """Version two freezes the exact advisor payload and ONE explicitly chosen model."""
    text = request.visible_payload()
    if len(text.encode()) > 32768:
        raise ValueError("Combined request exceeds the 32768-byte local limit")
    reference = request.research_reference
    base = prepare_quote(
        LiveDraft(
            instruction="Selected advisor request",
            source_code="The exact advisor payload is frozen below.",
            workload=reference.workload if reference else "chat.light",
        ),
        run_id,
        created_at,
    )
    preview = build_preflight(request)
    index = 0 if request.selected_model == "compact" else 1
    models = base["models"]
    assert isinstance(models, list)
    rates = RATES[index]
    task = next(
        (
            key
            for key in ("clamp", "discount", "merge")
            if text == prompt(EXERCISES[key])
        ),
        None,
    )
    base.update(
        schema_version=2,
        execution_mode="selected_model",
        draft=request.model_dump(mode="json"),
        exact_payload=text,
        prompt_sha256=hashlib.sha256(text.encode()).hexdigest(),
        models=[models[index]],
        generation_calls=1,
        token_count_calls=1,
        metadata_reads=1,
        quality_task=task,
        precall_decision=preview.decision.model_dump(mode="json"),
        estimated_cost_usd=str((4096 * rates[0] + 4096 * rates[1]) / 1_000_000),
        stress_cost_usd=str((4096 * rates[0] + 8192 * rates[1]) / 1_000_000),
        research=(
            preview.research_reference.model_dump(mode="json")
            if preview.research_reference
            else None
        ),
        quality_note=(
            "Reference plus four seeded-fault checks for the exact unchanged reviewed task."
            if task
            else "Quality not evaluated: this custom draft has no matching reviewed contract. Returned Python will not be executed."
        ),
    )
    del base["plan_sha256"]
    base["plan_sha256"] = digest(base)
    return base


def quote_task(quote: dict[str, object]) -> DecisionTask | None:
    """Versioned task access keeps legacy two-model plans byte-for-byte unchanged."""
    draft = quote["draft"]
    assert isinstance(draft, dict)
    value = (
        quote.get("quality_task")
        if quote.get("schema_version") == 2
        else draft.get("quality_task")
    )
    if value is None or value in ("clamp", "discount", "merge"):
        return value
    raise ValueError("Invalid reviewed quality task")


class LiveComparisonStore:
    """File IDs are validated; plans are immutable and runs reserve once."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def path(self, run_id: str, suffix: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise ValueError("Invalid comparison ID")
        return self.directory / f"{run_id}.{suffix}.json"

    def create(self, draft: LiveDraft) -> dict[str, object]:
        quote = prepare_quote(draft, uuid4().hex, datetime.now(UTC))
        return self.write_quote(quote)

    def create_selected(self, request: PreflightRequest) -> dict[str, object]:
        return self.write_quote(
            prepare_selected_quote(request, uuid4().hex, datetime.now(UTC))
        )

    def write_quote(self, quote: dict[str, object]) -> dict[str, object]:
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self.path(str(quote["id"]), "plan")
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            json.dump(quote, handle, indent=2)
        return self.view(str(quote["id"]))

    def load(self, run_id: str) -> dict[str, object]:
        raw = json.loads(self.path(run_id, "plan").read_text())
        created = datetime.fromisoformat(raw["created_at"])
        expected = (
            prepare_selected_quote(
                PreflightRequest.model_validate(raw["draft"]), run_id, created
            )
            if raw.get("schema_version") == 2
            else prepare_quote(LiveDraft.model_validate(raw["draft"]), run_id, created)
        )
        if raw != expected:
            raise ValueError("Frozen comparison plan changed; prepare a new quote")
        return expected

    def view(self, run_id: str) -> dict[str, object]:
        quote = self.load(run_id)
        result_path = self.path(run_id, "result")
        result = json.loads(result_path.read_text()) if result_path.exists() else None
        if result and result.get("plan_sha256") != quote["plan_sha256"]:
            raise ValueError("Results do not match this frozen plan")
        return {
            "quote": quote,
            "result": result,
            "status": result["status"] if result else "awaiting_terminal_approval",
            "approval_phrase": f"APPROVE {quote['plan_sha256']}",
            "execution_mode": "local_cli",
            "remaining_demo_runs": max(
                0, MAX_RUNS - len(list(self.directory.glob("slot-*.json")))
            ),
            "new_calls_from_this_read": 0,
        }

    def reserve(self, run_id: str, approval: str) -> dict[str, object]:
        quote = self.load(run_id)
        if datetime.now(UTC) > datetime.fromisoformat(str(quote["expires_at"])):
            raise ValueError("Quote expired; prepare and approve a fresh quote")
        if approval != f"APPROVE {quote['plan_sha256']}":
            raise ValueError("Approval does not match the frozen plan")
        state: dict[str, object] = {
            "plan_sha256": quote["plan_sha256"],
            "status": "reserved",
            "started_at": datetime.now(UTC).isoformat(),
            "operations": [],
            "responses": [],
            "known_catalog_cost_usd": "0",
            "billing_uncertain": False,
            "actual_carbon_g": None,
            "recommended_model": None,
        }
        # Exclusive creation is before any credentials/client/RPC. Crashes consume it.
        descriptor = os.open(
            self.path(run_id, "result"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        with os.fdopen(descriptor, "w") as handle:
            json.dump(state, handle, indent=2)
        for slot in range(MAX_RUNS):
            try:
                descriptor = os.open(
                    self.directory / f"slot-{slot}.json",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
            except FileExistsError:
                continue
            with os.fdopen(descriptor, "w") as handle:
                json.dump({"id": run_id, "plan_sha256": quote["plan_sha256"]}, handle)
            return state
        state.update(
            status="stopped",
            stop_reason="Three local demo run slots consumed; no provider calls sent",
        )
        self.save(run_id, state)
        raise ValueError("Three local demo run slots consumed")

    def save(self, run_id: str, state: dict[str, object]) -> None:
        path = self.path(run_id, "result")
        temporary = path.with_suffix(".writing")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            json.dump(state, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
