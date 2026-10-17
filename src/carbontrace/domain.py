"""Validated public contracts for offline comparison and scenario accounting."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TaskId = Literal[
    "clamp",
    "discount",
    "merge",
    "parse_bool",
    "valid_identifier",
    "ceil_div",
    "shipping_cost",
    "stable_unique",
    "chunks",
    "top_k",
    "slugify",
    "truncate",
    "collapse_whitespace",
    "inclusive_range",
]


class Contract(BaseModel):
    """Reject unknown fields and non-finite numbers at the API boundary."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)


class Interval(Contract):
    """Non-negative bounds; these are assumptions, not confidence intervals."""

    low: float = Field(ge=0)
    high: float = Field(ge=0)

    @model_validator(mode="after")
    def ordered(self) -> Interval:
        """Reject inverted intervals."""
        if self.high < self.low:
            raise ValueError("Upper bound must be at least the lower bound")
        return self


class HardwareScenario(Contract):
    """Explicit illustrative inputs, with no claim about provider hardware."""

    compact_power_w: Interval
    strong_power_w: Interval
    pue: float = Field(ge=1, le=3)
    grid_g_per_kwh: float = Field(ge=0, le=2000)


class CompareRequest(Contract):
    """Choose a curated exercise and an acceptance threshold."""

    task_id: TaskId = "clamp"
    minimum_detection: int = Field(default=100, ge=1, le=100)
    scenario: HardwareScenario | None = None


class AssertionResult(Contract):
    """Result of a literal assertion against the correct implementation."""

    title: str
    passed: bool
    detail: str


class MutationResult(Contract):
    """Whether the suite detects one deliberately seeded defect."""

    name: str
    description: str
    detected: bool


class QualityResult(Contract):
    """Local quality evidence restricted to the bundled exercise."""

    assertions: list[AssertionResult]
    mutations: list[MutationResult]
    correct_implementation_passes: bool
    detected: int
    total_mutations: int
    detection_percent: float


class SimulatedUsage(Contract):
    """Illustrative inference telemetry; never returned by a model provider."""

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    elapsed_seconds: float = Field(ge=0)
    provenance: Literal["scripted_fixture"] = "scripted_fixture"


class ImpactResult(Contract):
    """Operational electricity and GWP from explicitly assumed inputs."""

    energy_wh: Interval
    carbon_g: Interval
    methodology: Literal["allocated-power-v1"] = "allocated-power-v1"
    provenance: Literal["illustrative_scenario"] = "illustrative_scenario"


class Attempt(Contract):
    """A fixture replay, its actual local checks, and illustrative usage."""

    profile: Literal["compact", "strong"]
    name: str
    suite_code: str
    quality: QualityResult
    accepted: bool
    usage: SimulatedUsage
    impact: ImpactResult | None


class PolicyResult(Contract):
    """All attempts, including failed attempts, in one execution policy."""

    attempts: list[Attempt]
    accepted: bool
    final_profile: str | None
    total_tokens: int
    total_seconds: float
    impact: ImpactResult | None


class Comparison(Contract):
    """Exportable evidence with explicit simulation and measurement boundaries."""

    id: str
    created_at: str
    task_id: str
    task_title: str
    minimum_detection: int
    mode: Literal["offline_fixture"] = "offline_fixture"
    live_model_calls: Literal[0] = 0
    baseline: PolicyResult
    carbontrace: PolicyResult
    outcome: Literal["compact_accepted", "escalated", "quality_failed"]
    impact_comparison: Literal["unavailable", "lower", "higher", "overlap"]
    explanation: str
    scenario: HardwareScenario | None
