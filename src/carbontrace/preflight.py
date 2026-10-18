"""Offline pre-send planning, with distinct observed evidence and assumptions.

This module never loads credentials, creates a provider client, executes supplied
code, or persists drafts. There are deliberately no provider energy coefficients.
"""

from __future__ import annotations

import hashlib
import math
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from carbontrace.domain import (
    Contract,
    HardwareScenario,
    ImpactResult,
    Interval,
    TaskId,
)
from carbontrace.impact import estimate_operational_impact
from carbontrace.research import (
    ResearchRequest,
    ResearchResult,
    Workload,
    compare_research,
)

Role = Literal["compact", "strong"]


class Observation(Contract):
    """One real saved pilot response, not a forecast of the next response."""

    task_id: TaskId
    prompt_sha256: str
    input_tokens: int = Field(ge=1)
    generated_tokens: int = Field(ge=0)
    tests: int = Field(ge=1)
    detected: int = Field(ge=0)
    total_mutations: int = Field(ge=1)
    accepted: bool


class Profile(Contract):
    """Original pilot observations and dated catalog rates; no hardware guesses."""

    role: Role
    model_id: str
    input_usd_per_million: Decimal = Field(ge=0)
    generated_usd_per_million: Decimal = Field(ge=0)
    observations: list[Observation]


class Catalog(Contract):
    """Packaged research snapshot that works without the repository or network."""

    observed_on: str
    pricing_as_of: str
    pricing_source: str
    pricing_note: str
    source_report_sha256: str
    benchmark_sha256: str
    profiles: list[Profile]


@lru_cache(maxsize=1)
def catalog() -> Catalog:
    """Read only the sanitized local snapshot; never inspect user credentials."""
    return Catalog.model_validate_json(
        (Path(__file__).parent / "resources/preflight-comparison.json").read_text()
    )


class PreflightScenario(HardwareScenario):
    """Editable demonstration inputs, never a Gemini hardware specification."""

    compact_power_w: Interval = Field(default_factory=lambda: Interval(low=30, high=60))
    strong_power_w: Interval = Field(
        default_factory=lambda: Interval(low=120, high=180)
    )
    pue: float = Field(default=1.2, ge=1, le=3)
    grid_g_per_kwh: float = Field(default=400, ge=0, le=2000)
    input_tokens_per_second: float = Field(default=1000, ge=1, le=1_000_000)
    generated_tokens_per_second: float = Field(default=50, ge=1, le=1_000_000)
    provenance: Literal["illustrative_assumptions"] = "illustrative_assumptions"

    @model_validator(mode="after")
    def bounded_power(self) -> PreflightScenario:
        """Bound editable inputs before multiplying them into energy scenarios."""
        if max(self.compact_power_w.high, self.strong_power_w.high) > 100_000:
            raise ValueError("Allocated power must not exceed 100000 watts")
        return self


class WorkloadReference(Contract):
    """User-selected benchmark context, never inferred from prompt tokens."""

    workload: Workload
    grid_g_per_kwh: Decimal = Field(default=Decimal(400), ge=0, le=2000)


class PreflightRequest(Contract):
    """One visible request and a user-chosen generated-token planning scenario."""

    prompt: str = Field(min_length=1, max_length=32_768)
    context: str = Field(default="", max_length=32_768)
    selected_model: Role = "strong"
    generated_low: int = Field(default=256, ge=1, le=4096, strict=True)
    generated_high: int = Field(default=1024, ge=1, le=4096, strict=True)
    carbon_scenario: PreflightScenario | None = None
    research_reference: WorkloadReference | None = None

    @model_validator(mode="after")
    def valid_draft(self) -> PreflightRequest:
        """Reject blank instructions and inverted planning ranges."""
        if not self.prompt.strip():
            raise ValueError("Enter a prompt to preview")
        if self.generated_high < self.generated_low:
            raise ValueError(
                "Upper generated-token scenario must be at least the lower"
            )
        return self

    def visible_payload(self) -> str:
        """Make explicitly supplied context part of the counted and hashed payload."""
        if not self.context:
            return self.prompt
        return self.prompt + "\n\nAdditional context:\n" + self.context


class TokenScenarios(Contract):
    """Planning scenarios are not calibrated prediction intervals or hard bounds."""

    low: int
    high: int
    basis: Literal["observed_identical_pilot_prompt", "utf8_planning_heuristic"]
    note: str


class CostScenarios(Contract):
    """Catalog arithmetic before credits/tax/FX; not a quote or billing cap."""

    low: Decimal
    high: Decimal
    currency: Literal["USD"] = "USD"


class QualityEvidence(Contract):
    """Historical task evidence, with no new-draft correctness prediction."""

    scope: Literal["identical_pilot_prompt", "no_matching_pilot_prompt"]
    matched_observation: Observation | None
    pilot_accepted: int
    pilot_samples: int
    note: str


class ScenarioPreview(Contract):
    """Scenario duration and operational impact with explicit assumed provenance."""

    assumed_seconds: Interval
    impact: ImpactResult


class ModelPreview(Contract):
    """Separate token assumptions, price arithmetic, and historical quality."""

    role: Role
    model_id: str
    selected: bool
    input_tokens: TokenScenarios
    cost_usd: CostScenarios
    quality: QualityEvidence
    illustrative_impact: ScenarioPreview | None = None


class CarbonAvailability(Contract):
    """A missing energy attribution method must not become a fabricated score."""

    status: Literal["insufficient_evidence"] = "insufficient_evidence"
    energy_wh: None = None
    carbon_g: None = None
    note: str = (
        "No validated prompt-level energy profile is available. Published "
        "standardized-session references are separate. Actual serving "
        "hardware and electricity mix are unknown; API price is not an energy proxy."
    )


class PrecallDecision(Contract):
    """Actionable before execution; unfamiliar drafts never inherit task quality."""

    status: Literal[
        "supported_candidate", "insufficient_quality_evidence", "no_passing_candidate"
    ]
    evidence_scope: Literal[
        "exact_paired_prompt", "partial_exact_prompt", "unmatched_draft"
    ]
    recommended_role: Role | None = None
    recommended_model_id: str | None = None
    headline: str
    reasons: list[str]
    selected_matches_recommendation: bool | None = None
    caveat: str = (
        "Historical task evidence supports a candidate, not a guarantee for a new response. Actual prompt energy/carbon are unmeasured. No model call was made."
    )


def precall_decision(
    models: list[ModelPreview], selected: Role, reference: ResearchResult | None
) -> PrecallDecision:
    """Require both exact prompt observations before making a comparative choice."""
    matched = [m for m in models if m.quality.matched_observation is not None]
    if len(matched) != len(models):
        return PrecallDecision(
            status="insufficient_quality_evidence",
            evidence_scope="partial_exact_prompt" if matched else "unmatched_draft",
            headline="Choose a model manually: quality evidence is insufficient.",
            reasons=[
                "This draft has no matching quality evidence for both exact models. Editing the prompt or context removes the saved match.",
                "Token/cost scenarios can guide a budget decision, but cannot establish task quality.",
                "A CLEER workload is separate published context; it does not classify or predict this prompt.",
            ],
        )
    passed = [
        m
        for m in matched
        if (o := m.quality.matched_observation) is not None
        and o.accepted
        and o.tests > 0
        and o.total_mutations > 0
        and o.detected == o.total_mutations
    ]
    if not passed:
        return PrecallDecision(
            status="no_passing_candidate",
            evidence_scope="exact_paired_prompt",
            headline="Neither saved candidate met the quality requirement.",
            reasons=[
                "A low price or environmental reference cannot override a failed quality gate."
            ],
        )
    energy = (
        {
            row.model_name: row.total_energy_wh
            for row in reference.models
            if row.available and row.total_energy_wh is not None
        }
        if reference
        else {}
    )
    names = {"compact": "Gemini 3.5 Flash-Lite", "strong": "Gemini 3.7 Flash"}
    use_energy = all(names[m.role] in energy for m in passed)
    chosen = min(
        passed,
        key=lambda m: (
            energy[names[m.role]] if use_energy else m.cost_usd.high,
            m.cost_usd.high,
            m.cost_usd.low,
        ),
    )
    reasons = [
        (
            "Both saved suites met this exact task's gate. Validate any new suite."
            if len(passed) == len(models)
            else "Only the passing saved candidate is eligible; a failing model cannot win on price or energy."
        ),
        f"At your chosen token scenarios, this model's estimated cost is US${chosen.cost_usd.low}–US${chosen.cost_usd.high}; output size is assumed.",
    ]
    reasons.append(
        "Among eligible candidates, this model has the lower published facility-energy reference for your selected CLEER workload. This is not measured request-carbon savings."
        if use_energy and len(passed) > 1
        else "No environmental ranking was needed to select a candidate; without a workload reference, cost scenarios break ties between passing candidates."
    )
    return PrecallDecision(
        status="supported_candidate",
        evidence_scope="exact_paired_prompt",
        recommended_role=chosen.role,
        recommended_model_id=chosen.model_id,
        headline=f"Suggested candidate: {names[chosen.role]}",
        reasons=reasons,
        selected_matches_recommendation=selected == chosen.role,
    )


class PreflightResult(Contract):
    """Exportable, credential-free preview; includes no prompt text or execution."""

    mode: Literal["offline_preflight"] = "offline_preflight"
    live_model_calls: Literal[0] = 0
    prompt_sha256: str
    visible_utf8_bytes: int
    selected_model: Role
    generated_low: int
    generated_high: int
    generated_note: str
    pricing_as_of: str
    pricing_source: str
    pricing_note: str
    observed_on: str
    source_report_sha256: str
    models: list[ModelPreview]
    carbon: CarbonAvailability
    research_reference: ResearchResult | None = None
    carbon_scenario: PreflightScenario | None
    carbon_scenario_note: str = (
        "Demonstration assumptions only; not measured or calibrated to either Gemini "
        "model. Differences follow the assumed power values, not provider evidence. "
        "Ranges are sensitivity scenarios, not statistical confidence intervals. "
        "Operational electricity only; excludes training, manufacture, networking, "
        "end-user devices, later requests, and retries."
    )
    guidance: str
    scope_note: str
    decision: PrecallDecision


def build_preflight(request: PreflightRequest) -> PreflightResult:
    """Compare one visible payload locally without making a generation request."""
    evidence = catalog()
    payload = request.visible_payload().encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    previews: list[ModelPreview] = []
    for profile in evidence.profiles:
        match = next(
            (row for row in profile.observations if row.prompt_sha256 == digest), None
        )
        if match is not None:
            tokens = TokenScenarios(
                low=match.input_tokens,
                high=match.input_tokens,
                basis="observed_identical_pilot_prompt",
                note="Previously reported for this identical pilot prompt; not a fresh token count.",
            )
        else:
            tokens = TokenScenarios(
                low=max(1, math.ceil(len(payload) / 6)),
                high=max(1, math.ceil(len(payload) / 2)),
                basis="utf8_planning_heuristic",
                note="Local 2–6 UTF-8 bytes/token scenarios; actual tokenization may fall outside this range.",
            )
        divisor = Decimal(1_000_000)
        cost = CostScenarios(
            low=(
                tokens.low * profile.input_usd_per_million
                + request.generated_low * profile.generated_usd_per_million
            )
            / divisor,
            high=(
                tokens.high * profile.input_usd_per_million
                + request.generated_high * profile.generated_usd_per_million
            )
            / divisor,
        )
        scenario_preview = None
        if request.carbon_scenario is not None:
            scenario = request.carbon_scenario
            power = (
                scenario.compact_power_w
                if profile.role == "compact"
                else scenario.strong_power_w
            )
            seconds = Interval(
                low=tokens.low / scenario.input_tokens_per_second
                + request.generated_low / scenario.generated_tokens_per_second,
                high=tokens.high / scenario.input_tokens_per_second
                + request.generated_high / scenario.generated_tokens_per_second,
            )
            # Both non-negative scenario endpoints vary together; no midpoint or
            # observed network latency is substituted for allocated compute time.
            lower = estimate_operational_impact(
                power, seconds.low, scenario.pue, scenario.grid_g_per_kwh
            )
            upper = estimate_operational_impact(
                power, seconds.high, scenario.pue, scenario.grid_g_per_kwh
            )
            scenario_preview = ScenarioPreview(
                assumed_seconds=seconds,
                impact=ImpactResult(
                    energy_wh=Interval(
                        low=lower.energy_wh.low, high=upper.energy_wh.high
                    ),
                    carbon_g=Interval(low=lower.carbon_g.low, high=upper.carbon_g.high),
                ),
            )
        previews.append(
            ModelPreview(
                role=profile.role,
                model_id=profile.model_id,
                selected=profile.role == request.selected_model,
                input_tokens=tokens,
                cost_usd=cost,
                illustrative_impact=scenario_preview,
                quality=QualityEvidence(
                    scope=(
                        "identical_pilot_prompt"
                        if match
                        else "no_matching_pilot_prompt"
                    ),
                    matched_observation=match,
                    pilot_accepted=sum(row.accepted for row in profile.observations),
                    pilot_samples=len(profile.observations),
                    note=(
                        "One historical response passed the seeded-fault gate. A new response still needs validation."
                        if match
                        else (
                            "No saved response matches this draft. The three-function pilot cannot establish quality for it."
                            if profile.observations
                            else "No saved pilot responses for Gemini 3.7 Flash. Gemini 3.8 results are not transferred to this model."
                        )
                    ),
                ),
            )
        )
    reference = (
        compare_research(
            ResearchRequest(
                workload=request.research_reference.workload,
                sessions=1,
                grid_g_per_kwh=request.research_reference.grid_g_per_kwh,
            )
        )
        if request.research_reference
        else None
    )
    decision = precall_decision(previews, request.selected_model, reference)
    return PreflightResult(
        prompt_sha256=digest,
        visible_utf8_bytes=len(payload),
        selected_model=request.selected_model,
        generated_low=request.generated_low,
        generated_high=request.generated_high,
        generated_note="User-chosen output plus reasoning scenarios, not a response-length prediction or enforced limit.",
        pricing_as_of=evidence.pricing_as_of,
        pricing_source=evidence.pricing_source,
        pricing_note=evidence.pricing_note,
        observed_on=evidence.observed_on,
        source_report_sha256=evidence.source_report_sha256,
        models=previews,
        carbon=CarbonAvailability(),
        research_reference=reference,
        carbon_scenario=request.carbon_scenario,
        decision=decision,
        guidance=" ".join(decision.reasons),
        scope_note="One visible request only. Hidden agent context, later tool calls, retries, and quality-gate runtime are excluded. Your draft is not saved by this endpoint.",
    )
