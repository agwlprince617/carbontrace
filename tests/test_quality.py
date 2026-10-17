"""Check quality discrimination, literal-data execution, and export parity."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from carbontrace.benchmarks import (
    EXERCISES,
    clamp,
    discounted_total,
    merge_intervals,
)
from carbontrace.benchmarks import (
    TestCase as Case,
)
from carbontrace.quality import Profile, check_assertion, evaluate_suite, render_suite


@pytest.mark.parametrize("task_id", ["clamp", "discount", "merge"])
def test_thorough_suite_catches_all_seeded_faults(task_id: str) -> None:
    """Fixtures must pass correct behavior and discriminate every known defect."""
    quality = evaluate_suite(task_id, "strong")
    assert quality.correct_implementation_passes
    assert quality.detection_percent == 100
    assert all(item.detected for item in quality.mutations)
    assert all(item.passed for item in quality.assertions)


def test_compact_suite_is_not_unconditionally_accepted() -> None:
    """Simple exercises succeed, but the interval fixture has real blind spots."""
    assert evaluate_suite("clamp", "compact").detection_percent == 100
    assert evaluate_suite("discount", "compact").detection_percent == 100
    weak = evaluate_suite("merge", "compact")
    assert weak.correct_implementation_passes
    assert weak.detection_percent == 0


def test_literal_assertions_distinguish_wrong_values_and_exceptions() -> None:
    """Wrong values, missing exceptions, and unexpected exceptions all fail."""
    assert not check_assertion(clamp, Case("wrong expected", (5, 0, 10), 0)).passed
    assert not check_assertion(
        clamp, Case("missing error", (5, 0, 10), raises=ValueError)
    ).passed
    assert not check_assertion(clamp, Case("unexpected error", (5, 10, 0), 0)).passed
    assert check_assertion(
        clamp, Case("expected error", (5, 10, 0), raises=ValueError)
    ).passed


@pytest.mark.parametrize(
    "value,expected", [(-1, 0), (0, 0), (5, 5), (10, 10), (11, 10)]
)
def test_clamp_contract(value: int, expected: int) -> None:
    """Inclusive bounds and interior values follow the exercise requirements."""
    assert clamp(value, 0, 10) == expected


@pytest.mark.parametrize("args", [(-1, 1, 0), (100, 0, 0), (100, 1, -1), (100, 1, 101)])
def test_discount_rejects_invalid_orders(args: tuple[int, int, int]) -> None:
    """Invalid price, quantity, and discount values cannot pass silently."""
    with pytest.raises(ValueError):
        discounted_total(*args)


def test_merge_preserves_input_and_handles_touching_nested_unsorted_intervals() -> None:
    """The correct implementation merges consistently without input mutation."""
    source = [[5, 8], [1, 10], [2, 3], [10, 11]]
    assert merge_intervals(source) == [[1, 11]]
    assert source == [[5, 8], [1, 10], [2, 3], [10, 11]]


@pytest.mark.parametrize("task_id", ["clamp", "discount", "merge"])
@pytest.mark.parametrize("profile", ["compact", "strong"])
def test_downloaded_pytest_suites_actually_run(
    task_id: str, profile: Profile, tmp_path: Path
) -> None:
    """Run only our own generated fixture exports in a separate local process."""
    code = render_suite(task_id, profile)
    ast.parse(code)
    (tmp_path / "subject.py").write_text(EXERCISES[task_id].source)
    (tmp_path / "test_export.py").write_text(code)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--override-ini",
            "addopts=",
            "test_export.py",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
        env={"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONIOENCODING": "utf-8"},
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
