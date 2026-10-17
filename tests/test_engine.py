"""End-to-end policy accounting and transparent simulation provenance."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import carbontrace.engine as engine
from carbontrace.__main__ import main
from carbontrace.domain import Attempt, CompareRequest, HardwareScenario
from carbontrace.quality import Profile


def test_compact_pass_is_not_presented_as_measured_savings() -> None:
    """Offline evidence must carry no live-model or energy measurement claim."""
    result = engine.build_comparison(CompareRequest(task_id="clamp"))
    assert result.outcome == "compact_accepted"
    assert len(result.carbontrace.attempts) == 1
    assert result.carbontrace.accepted and result.baseline.accepted
    assert result.live_model_calls == 0
    assert result.impact_comparison == "unavailable"
    assert result.carbontrace.impact is None
    assert result.carbontrace.attempts[0].usage.provenance == "scripted_fixture"


def test_escalation_counts_rejected_attempt(scenario: HardwareScenario) -> None:
    """A failed compact attempt adds its tokens, duration, and assumed energy."""
    result = engine.build_comparison(CompareRequest(task_id="merge", scenario=scenario))
    selected = result.carbontrace
    assert result.outcome == "escalated"
    assert selected.final_profile == "strong"
    assert [item.accepted for item in selected.attempts] == [False, True]
    assert selected.total_tokens == sum(
        item.usage.input_tokens + item.usage.output_tokens for item in selected.attempts
    )
    assert selected.total_tokens > result.baseline.total_tokens
    assert selected.total_seconds == 10
    assert selected.impact is not None and result.baseline.impact is not None
    assert selected.impact.energy_wh.low > result.baseline.impact.energy_wh.low


def test_explicit_scenario_can_be_compared(scenario: HardwareScenario) -> None:
    """The compact exercise yields lower bounds only under stated assumptions."""
    result = engine.build_comparison(
        CompareRequest(task_id="discount", scenario=scenario)
    )
    assert result.impact_comparison == "lower"
    assert result.carbontrace.impact is not None
    assert result.carbontrace.impact.provenance == "illustrative_scenario"


def test_failed_final_quality_cannot_support_efficiency_recommendation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even lower usage cannot justify accepting an incorrect suite."""
    original = engine.replay_attempt

    def failing(
        task_id: str, profile: Profile, minimum: int, scenario: HardwareScenario | None
    ) -> Attempt:
        """Emulate a future provider producing an unacceptable final suite."""
        return original(task_id, profile, minimum, scenario).model_copy(
            update={"accepted": False}
        )

    monkeypatch.setattr(engine, "replay_attempt", failing)
    result = engine.build_comparison(CompareRequest())
    assert result.outcome == "quality_failed"
    assert result.carbontrace.final_profile is None
    assert result.impact_comparison == "unavailable"


def test_cli_exports_all_exercises(tmp_path: Path) -> None:
    """Produce shareable evidence without any model client."""
    target = tmp_path / "nested" / "evidence.json"
    main(["--output", str(target)])
    records = json.loads(target.read_text())
    assert len(records) == 3
    assert all(item["mode"] == "offline_fixture" for item in records)
    assert records[-1]["outcome"] == "escalated"
