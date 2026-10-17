"""Task-scoped decisions from saved suite checks and separate session references."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from carbontrace.benchmark import manifest, prompt
from carbontrace.benchmarks import EXERCISES
from carbontrace.domain import Contract
from carbontrace.research import (
    ResearchRequest,
    ResearchResult,
    Workload,
    compare_research,
)

DecisionTask = Literal["clamp", "discount", "merge"]
ModelId = Literal["gemini-3.5-flash-lite", "gemini-3.7-flash"]
MODELS: tuple[ModelId, ModelId] = ("gemini-3.5-flash-lite", "gemini-3.7-flash")
NAMES = ("Gemini 3.5 Flash-Lite", "Gemini 3.7 Flash")
EVIDENCE_SHA256 = "c42ee5be4564a63728986a17849c2e61bfdca35d3e748dc83aeb25adab66a1e8"


class GateExecution(Contract):
    """Saved container outcome; failures and infrastructure errors stay distinct."""

    status: str
    tests: int = Field(ge=0)
    failures: int = Field(ge=0)
    errors: int = Field(ge=0)
    skipped: int = Field(ge=0)

    @property
    def clean_pass(self) -> bool:
        return (
            self.status == "passed"
            and self.tests > 0
            and not (self.failures or self.errors or self.skipped)
        )

    @property
    def detected(self) -> bool:
        return (
            self.status == "failed"
            and self.tests > 0
            and self.failures > 0
            and not (self.errors or self.skipped)
        )


class SuiteEvidence(Contract):
    """Sanitized response and container checks, with no executable suite text."""

    task_id: DecisionTask
    model_id: ModelId
    model_version: str
    prompt_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    suite_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    image_id: str
    reference: GateExecution
    mutations: dict[str, GateExecution]
    input_tokens: int = Field(ge=1)
    candidate_tokens: int = Field(ge=0)
    thinking_tokens: int = Field(ge=0)
    catalog_cost_usd: Decimal = Field(ge=0)

    @model_validator(mode="after")
    def bound_to_task(self) -> SuiteEvidence:
        """A sibling model, changed prompt or missing bug cannot borrow evidence."""
        exercise = EXERCISES[self.task_id]
        if self.prompt_sha256 != hashlib.sha256(prompt(exercise).encode()).hexdigest():
            raise ValueError("Decision evidence prompt differs from frozen task")
        if not self.model_version.startswith(self.model_id):
            raise ValueError("Decision evidence model version differs")
        if set(self.mutations) != {item.name for item in exercise.mutations}:
            raise ValueError("Decision evidence must account for every seeded fault")
        return self

    @property
    def accepted(self) -> bool:
        return self.reference.clean_pass and all(
            row.detected for row in self.mutations.values()
        )


class EvidenceBundle(Contract):
    """Integrity-checked research snapshot; source report remains independently saved."""

    source_report_sha256: str
    benchmark_sha256: str
    observed_on: str
    cost_basis: str
    usage_note: str
    records: list[SuiteEvidence]


@lru_cache(maxsize=1)
def saved_evidence() -> EvidenceBundle:
    path = Path(__file__).parent / "resources/decision-evidence.json"
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != EVIDENCE_SHA256:
        raise ValueError("Decision evidence integrity check failed")
    evidence = EvidenceBundle.model_validate_json(content)
    if evidence.benchmark_sha256 != manifest()["sha256"]:
        raise ValueError("Decision benchmark differs from saved evidence")
    if len({(r.task_id, r.model_id) for r in evidence.records}) != len(
        evidence.records
    ):
        raise ValueError("Duplicate decision evidence")
    return evidence


class DecisionRequest(Contract):
    """One owned task; custom code and browser execution approvals are not accepted."""

    task_id: DecisionTask = "clamp"
    workload: Workload
    grid_g_per_kwh: Decimal = Field(default=Decimal(400), ge=0, le=2000)


class DecisionModel(Contract):
    model_id: ModelId
    model_name: str
    evidence: SuiteEvidence | None
    gate: Literal["passed", "failed", "not_tested"]
    detected_faults: int | None
    total_faults: int


class DecisionResult(Contract):
    mode: Literal["saved_task_decision"] = "saved_task_decision"
    live_model_calls: Literal[0] = 0
    task_id: DecisionTask
    task_title: str
    requirements: str
    source: str
    prompt_sha256: str
    benchmark_sha256: str
    evidence_source_report_sha256: str
    evidence_observed_on: str
    cost_basis: str
    usage_note: str
    models: list[DecisionModel]
    reference: ResearchResult
    status: Literal["awaiting_pair", "both_passed", "one_passed", "neither_passed"]
    recommended_model: ModelId | None
    explanation: str
    known_comparison_cost_usd: Decimal
    limitations: list[str] = [
        "One saved response per available model/task, not repeated validation or a general quality ranking. Benchmark requirements still need independent human review.",
        "CLEER is a separate standardized-session reference. Task tokens, tests and response duration do not calibrate its energy to this request.",
        "Observed usage is provider-reported. Cost is catalog arithmetic, not a verified invoice. Comparison cost includes both available responses, not only a selected model.",
        "Inference energy, quality-check compute, retries and workflow carbon are not measured. No actual carbon saving is established.",
        "A missing model response blocks the paired decision; historical Gemini 3.8 results are not attributed to Gemini 3.7.",
    ]


def build_decision(
    request: DecisionRequest, evidence: EvidenceBundle | None = None
) -> DecisionResult:
    """Apply the gate first; never select an untested or failing low-energy model."""
    bundle = evidence if evidence is not None else saved_evidence()
    exercise = EXERCISES[request.task_id]
    models: list[DecisionModel] = []
    for model_id, name in zip(MODELS, NAMES, strict=True):
        row = next(
            (
                r
                for r in bundle.records
                if r.task_id == request.task_id and r.model_id == model_id
            ),
            None,
        )
        models.append(
            DecisionModel(
                model_id=model_id,
                model_name=name,
                evidence=row,
                gate=(
                    "not_tested"
                    if row is None
                    else "passed" if row.accepted else "failed"
                ),
                detected_faults=(
                    sum(item.detected for item in row.mutations.values())
                    if row
                    else None
                ),
                total_faults=len(exercise.mutations),
            )
        )
    reference = compare_research(
        ResearchRequest(
            model_a=NAMES[0],
            model_b=NAMES[1],
            workload=request.workload,
            sessions=1,
            grid_g_per_kwh=request.grid_g_per_kwh,
        )
    )
    recommended: ModelId | None = None
    status: Literal["awaiting_pair", "both_passed", "one_passed", "neither_passed"]
    if any(row.gate == "not_tested" for row in models):
        status = "awaiting_pair"
        explanation = "Paired decision pending: both exact models need a saved suite evaluated against this task's reference and every seeded fault. Environmental references alone do not establish task suitability."
    elif all(row.gate == "passed" for row in models):
        status = "both_passed"
        # Both exact CLEER names have all six workloads; lower facility energy is
        # the declared tie-breaker only after both suites pass the full task gate.
        energy = [row.total_energy_wh for row in reference.models]
        first, second = energy
        assert first is not None and second is not None
        chosen = 0 if first <= second else 1
        recommended = models[chosen].model_id
        explanation = f"Both saved suites passed this task's quality gate. {models[chosen].model_name} has the lower published facility-energy mean for the selected CLEER workload, making it a candidate for this task. This is benchmark context, not measured request-carbon savings or a prediction that a new suite will pass."
    elif any(row.gate == "passed" for row in models):
        status = "one_passed"
        chosen_model = next(row for row in models if row.gate == "passed")
        recommended = chosen_model.model_id
        explanation = f"Only {chosen_model.model_name}'s saved suite passed the full task gate. Prefer the passing candidate for this example, regardless of the other model's environmental reference. A new response still needs validation."
    else:
        status = "neither_passed"
        explanation = "Neither saved suite passed the full task gate. No candidate is recommended; lower benchmark energy cannot justify incorrect or incomplete tests."
    return DecisionResult(
        task_id=request.task_id,
        task_title=exercise.title,
        requirements=exercise.description,
        source=exercise.source,
        prompt_sha256=hashlib.sha256(prompt(exercise).encode()).hexdigest(),
        benchmark_sha256=bundle.benchmark_sha256,
        evidence_source_report_sha256=bundle.source_report_sha256,
        evidence_observed_on=bundle.observed_on,
        cost_basis=bundle.cost_basis,
        usage_note=bundle.usage_note,
        models=models,
        reference=reference,
        status=status,
        recommended_model=recommended,
        explanation=explanation,
        known_comparison_cost_usd=sum(
            (row.evidence.catalog_cost_usd for row in models if row.evidence),
            Decimal(0),
        ),
    )
