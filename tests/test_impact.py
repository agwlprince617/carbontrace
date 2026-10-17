"""Unit conversions, interval arithmetic, and failure boundaries."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from carbontrace.domain import Interval
from carbontrace.impact import (
    compare_intervals,
    estimate_operational_impact,
    sum_impacts,
)


def test_dimensional_accounting_and_aggregation() -> None:
    """100 W for one hour at PUE 1.2 is 120 Wh, or 48 g at 400 g/kWh."""
    result = estimate_operational_impact(Interval(low=100, high=200), 3600, 1.2, 400)
    assert result.energy_wh.low == pytest.approx(120)
    assert result.energy_wh.high == pytest.approx(240)
    assert result.carbon_g.low == pytest.approx(48)
    assert result.carbon_g.high == pytest.approx(96)
    summed = sum_impacts([result, result])
    assert summed is not None
    assert summed.carbon_g.high == pytest.approx(192)
    assert sum_impacts([]) is None


def test_only_disjoint_ranges_support_direction() -> None:
    """Overlapping assumptions must not produce a forced savings claim."""
    base = estimate_operational_impact(Interval(low=100, high=200), 3600, 1, 400)
    low = estimate_operational_impact(Interval(low=10, high=20), 3600, 1, 400)
    high = estimate_operational_impact(Interval(low=300, high=400), 3600, 1, 400)
    assert compare_intervals(base, low) == "lower"
    assert compare_intervals(base, high) == "higher"
    assert compare_intervals(base, base) == "overlap"
    assert compare_intervals(base, None) == "unavailable"
    assert compare_intervals(None, base) == "unavailable"


@pytest.mark.parametrize(
    "seconds,pue,grid",
    [
        (-1, 1, 400),
        (1, 0.9, 400),
        (1, 1, -1),
        (float("nan"), 1, 400),
        (1, float("inf"), 400),
    ],
)
def test_invalid_physical_inputs_rejected(
    seconds: float, pue: float, grid: float
) -> None:
    """Do not silently generate impossible or non-finite results."""
    with pytest.raises(ValueError):
        estimate_operational_impact(Interval(low=1, high=2), seconds, pue, grid)


@pytest.mark.parametrize("low,high", [(2, 1), (-1, 1), (0, float("inf"))])
def test_invalid_intervals_rejected(low: float, high: float) -> None:
    """Require finite, non-negative ordered bounds."""
    with pytest.raises(ValidationError):
        Interval(low=low, high=high)


def test_zero_inputs_remain_zero() -> None:
    """A zero-duration scenario is distinct from an unavailable estimate."""
    result = estimate_operational_impact(Interval(low=0, high=100), 0, 1, 400)
    assert result.energy_wh.high == 0
    assert result.carbon_g.high == 0
