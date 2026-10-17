"""Benchmark diversity, frozen split, prompt isolation, and CLI safeguards."""

from __future__ import annotations

import json
from pathlib import Path
from typing import get_args

import pytest

from carbontrace.benchmark import fingerprint, main, manifest, prompt, run_plan
from carbontrace.benchmarks import EXERCISES
from carbontrace.domain import TaskId
from carbontrace.quality import check_assertion, evaluate_suite


def test_split_and_plan_are_reproducible_and_bounded() -> None:
    """Twenty functions are split before any provider response can influence routing."""
    catalog = manifest()
    assert catalog == manifest()
    assert catalog["total_functions"] == 20
    assert catalog["development_functions"] == 14
    assert catalog["holdout_functions"] == 6
    assert set(get_args(TaskId)) == {
        item.id for item in EXERCISES.values() if item.split == "development"
    }
    smoke = run_plan()
    full = run_plan(True)
    assert smoke["generation_calls"] == 6
    assert full["generation_calls"] == 80
    assert smoke["automatic_retries"] == 0
    assert smoke["models"] == {"compact": None, "strong": None}
    assert smoke["cost_estimate"] is None


def test_checked_in_manifest_matches_frozen_catalog() -> None:
    """A requirement, oracle, mutation, split, or source edit requires manifest review."""
    root = Path(__file__).resolve().parents[1]
    assert json.loads((root / "docs/benchmark-manifest.json").read_text()) == manifest()
    assert json.loads((root / "docs/smoke-plan.json").read_text()) == run_plan()
    assert json.loads((root / "docs/full-plan.json").read_text()) == run_plan(True)


@pytest.mark.parametrize("task", list(EXERCISES))
def test_every_reference_and_mutation_has_independent_literal_evidence(
    task: str,
) -> None:
    """Exercise all branches without short-circuiting at the first detected fault."""
    exercise = EXERCISES[task]
    assert len(exercise.mutations) == 4
    assert all(
        check_assertion(exercise.function, case).passed
        for case in exercise.strong_cases
    )
    for mutation in exercise.mutations:
        outcomes = [
            check_assertion(mutation.target, case).passed
            for case in exercise.strong_cases
        ]
        assert not all(outcomes), (task, mutation.name)
    assert evaluate_suite(task, "strong").detection_percent == 100
    assert len(fingerprint(exercise)) == 64
    generated_prompt = prompt(exercise)
    assert exercise.source in generated_prompt
    assert all(
        f"def {mutation.target.__name__}(" not in generated_prompt
        for mutation in exercise.mutations
    )


def test_cli_exports_offline_artifacts_and_refuses_holdout_execution(
    tmp_path: Path,
) -> None:
    """Planning is offline, and holdout evaluation requires an explicit CLI choice."""
    output = tmp_path / "manifest.json"
    main(["manifest", "--output", str(output)])
    assert json.loads(output.read_text())["total_functions"] == 20
    main(["plan", "--output", str(output)])
    assert json.loads(output.read_text())["generation_calls"] == 6
    with pytest.raises(SystemExit):
        main(
            [
                "evaluate",
                "--output",
                str(output),
                "--task",
                "rotate",
                "--suite",
                "missing.py",
                "--image",
                "missing",
            ]
        )
    with pytest.raises(SystemExit):
        main(
            [
                "evaluate",
                "--output",
                str(output),
                "--task",
                "clamp",
                "--suite",
                "missing.py",
                "--image",
                "missing",
            ]
        )
