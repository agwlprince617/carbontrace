"""Compare always-strong and quality-gated fixture policies without inference."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from carbontrace.benchmarks import EXERCISES
from carbontrace.domain import (
    Attempt,
    CompareRequest,
    Comparison,
    HardwareScenario,
    PolicyResult,
    SimulatedUsage,
)
from carbontrace.impact import (
    compare_intervals,
    estimate_operational_impact,
    sum_impacts,
)
from carbontrace.quality import Profile, evaluate_suite, render_suite


def replay_attempt(
    task_id: str,
    profile: Profile,
    minimum_detection: int,
    scenario: HardwareScenario | None,
) -> Attempt:
    """Check an original fixture and attach clearly synthetic usage assumptions."""
    quality = evaluate_suite(task_id, profile)
    code = render_suite(task_id, profile)
    usage = SimulatedUsage(
        input_tokens=math.ceil(len(EXERCISES[task_id].source) / 4),
        output_tokens=math.ceil(len(code) / 4),
        elapsed_seconds=2.0 if profile == "compact" else 8.0,
    )
    impact = None
    if scenario:
        power = (
            scenario.compact_power_w
            if profile == "compact"
            else scenario.strong_power_w
        )
        impact = estimate_operational_impact(
            power, usage.elapsed_seconds, scenario.pue, scenario.grid_g_per_kwh
        )
    return Attempt(
        profile=profile,
        name="Compact fixture" if profile == "compact" else "Thorough fixture",
        suite_code=code,
        quality=quality,
        accepted=quality.correct_implementation_passes
        and quality.detection_percent >= minimum_detection,
        usage=usage,
        impact=impact,
    )


def aggregate_policy(attempts: list[Attempt]) -> PolicyResult:
    """Count every attempted generation, even if its test suite was rejected."""
    final = attempts[-1]
    return PolicyResult(
        attempts=attempts,
        accepted=final.accepted,
        final_profile=final.profile if final.accepted else None,
        total_tokens=sum(
            item.usage.input_tokens + item.usage.output_tokens for item in attempts
        ),
        total_seconds=sum(item.usage.elapsed_seconds for item in attempts),
        impact=sum_impacts(
            [item.impact for item in attempts if item.impact is not None]
        ),
    )


def build_comparison(request: CompareRequest) -> Comparison:
    """Replay two hypothetical policies and report the limits of the evidence."""
    strong = replay_attempt(
        request.task_id, "strong", request.minimum_detection, request.scenario
    )
    compact = replay_attempt(
        request.task_id, "compact", request.minimum_detection, request.scenario
    )
    baseline = aggregate_policy([strong])
    selected = aggregate_policy([compact] if compact.accepted else [compact, strong])
    outcome: Literal["quality_failed", "compact_accepted", "escalated"]
    if not baseline.accepted or not selected.accepted:
        outcome = "quality_failed"
        explanation = "A final suite fails the quality requirement. No efficiency recommendation is supported."
    elif compact.accepted:
        outcome = "compact_accepted"
        explanation = "The compact fixture meets the selected fault-detection threshold. No escalation is needed in this scripted example."
    else:
        outcome = "escalated"
        explanation = "The compact fixture misses required seeded faults. The policy escalates and counts both attempts; this example adds overhead."
    return Comparison(
        id=uuid4().hex,
        created_at=datetime.now(UTC).isoformat(),
        task_id=request.task_id,
        task_title=EXERCISES[request.task_id].title,
        minimum_detection=request.minimum_detection,
        baseline=baseline,
        carbontrace=selected,
        outcome=outcome,
        impact_comparison=(
            compare_intervals(baseline.impact, selected.impact)
            if baseline.accepted and selected.accepted
            else "unavailable"
        ),
        explanation=explanation,
        scenario=request.scenario,
    )
