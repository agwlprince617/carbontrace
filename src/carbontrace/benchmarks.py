"""Original reference functions, seeded bugs, and hand-authored fixture suites.

Nothing here is a provider response or a record of model performance. All callables
are project-owned. Request bodies can select IDs but cannot supply executable code.
"""

from __future__ import annotations

from carbontrace.exercise import Exercise as Exercise
from carbontrace.exercise import Mutation as Mutation
from carbontrace.exercise import Target as Target
from carbontrace.exercise import TestCase as TestCase
from carbontrace.expanded_catalog import EXTRA_EXERCISES


def clamp(value: int, lower: int, upper: int) -> int:
    """Clamp an integer to inclusive bounds; reject reversed bounds."""
    if lower > upper:
        raise ValueError("lower must not exceed upper")
    return min(max(value, lower), upper)


def discounted_total(price_cents: int, quantity: int, discount: int) -> int:
    """Apply an integer percent discount, rounding down to whole cents."""
    if price_cents < 0 or quantity < 1 or not 0 <= discount <= 100:
        raise ValueError("invalid order")
    return price_cents * quantity * (100 - discount) // 100


def merge_intervals(intervals: list[list[int]]) -> list[list[int]]:
    """Sort and merge overlapping or touching closed integer intervals."""
    if any(start > end for start, end in intervals):
        raise ValueError("reversed interval")
    result: list[list[int]] = []
    for start, end in sorted(intervals):
        if result and start <= result[-1][1]:
            result[-1][1] = max(result[-1][1], end)
        else:
            result.append([start, end])
    return result


def _clamp_lower(value: int, lower: int, upper: int) -> int:
    """Seed: move values below the lower bound one step too high."""
    return lower + 1 if value < lower else clamp(value, lower, upper)


def _clamp_upper(value: int, lower: int, upper: int) -> int:
    """Seed: move values above the upper bound one step too low."""
    return upper - 1 if value > upper else clamp(value, lower, upper)


def _clamp_reversed(value: int, lower: int, upper: int) -> int:
    """Seed: accept reversed bounds."""
    return min(max(value, lower), upper)


def _clamp_inside(value: int, lower: int, upper: int) -> int:
    """Seed: replace an interior value with the lower bound."""
    return lower if lower < value < upper else clamp(value, lower, upper)


def _discount_quantity(price_cents: int, quantity: int, discount: int) -> int:
    """Seed: ignore the quantity."""
    return discounted_total(price_cents, 1, discount)


def _discount_ignored(price_cents: int, quantity: int, discount: int) -> int:
    """Seed: ignore a valid discount."""
    discounted_total(price_cents, quantity, discount)
    return price_cents * quantity


def _discount_rounding(price_cents: int, quantity: int, discount: int) -> int:
    """Seed: round fractional cents up instead of down."""
    result = discounted_total(price_cents, quantity, discount)
    return result + int(price_cents * quantity * (100 - discount) % 100 != 0)


def _discount_validation(price_cents: int, quantity: int, discount: int) -> int:
    """Seed: omit order validation."""
    return price_cents * quantity * (100 - discount) // 100


def _merge_unsorted(intervals: list[list[int]]) -> list[list[int]]:
    """Seed: assume the input is already sorted."""
    result: list[list[int]] = []
    for start, end in intervals:
        if result and start <= result[-1][1]:
            result[-1][1] = max(result[-1][1], end)
        else:
            result.append([start, end])
    return result


def _merge_touching(intervals: list[list[int]]) -> list[list[int]]:
    """Seed: fail to merge touching boundaries."""
    if any(start > end for start, end in intervals):
        raise ValueError("reversed interval")
    result: list[list[int]] = []
    for start, end in sorted(intervals):
        if result and start < result[-1][1]:
            result[-1][1] = max(result[-1][1], end)
        else:
            result.append([start, end])
    return result


def _merge_shrink(intervals: list[list[int]]) -> list[list[int]]:
    """Seed: shrink a containing interval when merging a nested one."""
    result: list[list[int]] = []
    for start, end in sorted(intervals):
        if result and start <= result[-1][1]:
            result[-1][1] = end
        else:
            result.append([start, end])
    return result


def _merge_validation(intervals: list[list[int]]) -> list[list[int]]:
    """Seed: silently discard invalid intervals."""
    return merge_intervals([pair for pair in intervals if pair[0] <= pair[1]])


_clamp_cases = (
    TestCase("Below lower bound", (-2, 0, 10), 0),
    TestCase("Above upper bound", (12, 0, 10), 10),
    TestCase("Interior value", (5, 0, 10), 5),
    TestCase("Reversed bounds rejected", (5, 10, 0), raises=ValueError),
)
_discount_cases = (
    TestCase("Quantity and discount", (1000, 2, 10), 1800),
    TestCase("Fractional cents round down", (99, 1, 50), 49),
    TestCase("Invalid discount rejected", (100, 1, 101), raises=ValueError),
)
_merge_cases = (
    TestCase("Overlapping intervals", ([[1, 4], [2, 6]],), [[1, 6]]),
    TestCase("Empty input", ([],), []),
)

EXERCISES: dict[str, Exercise] = {
    "clamp": Exercise(
        id="clamp",
        title="Clamp a value",
        category="Validation",
        description="Keep an integer inside inclusive bounds. Reject reversed bounds and preserve interior values.",
        function=clamp,
        mutations=(
            Mutation("lower", "Lower bound is off by one", _clamp_lower),
            Mutation("upper", "Upper bound is off by one", _clamp_upper),
            Mutation("reversed", "Reversed bounds are accepted", _clamp_reversed),
            Mutation("inside", "Interior values are overwritten", _clamp_inside),
        ),
        compact_cases=_clamp_cases,
        strong_cases=_clamp_cases
        + (
            TestCase("Exact lower boundary", (0, 0, 10), 0),
            TestCase("Exact upper boundary", (10, 0, 10), 10),
        ),
    ),
    "discount": Exercise(
        id="discount",
        title="Apply an order discount",
        category="Arithmetic",
        description="Calculate an order total in cents, apply a percent discount, and round down. Reject invalid orders.",
        function=discounted_total,
        mutations=(
            Mutation("quantity", "Quantity is ignored", _discount_quantity),
            Mutation("discount", "Discount is ignored", _discount_ignored),
            Mutation("rounding", "Fractional cents round up", _discount_rounding),
            Mutation("validation", "Invalid orders are accepted", _discount_validation),
        ),
        compact_cases=_discount_cases,
        strong_cases=_discount_cases
        + (
            TestCase("Free order", (1000, 2, 100), 0),
            TestCase("Negative price rejected", (-1, 1, 0), raises=ValueError),
            TestCase("Zero quantity rejected", (100, 0, 0), raises=ValueError),
        ),
    ),
    "merge": Exercise(
        id="merge",
        title="Merge closed intervals",
        category="Intervals",
        description="Sort and merge overlapping or touching intervals. Preserve containing intervals and reject reversed pairs.",
        function=merge_intervals,
        mutations=(
            Mutation("sorting", "Unsorted input is mishandled", _merge_unsorted),
            Mutation("touching", "Touching boundaries stay separate", _merge_touching),
            Mutation(
                "containment", "Nested intervals shrink the result", _merge_shrink
            ),
            Mutation(
                "validation",
                "Reversed intervals are silently discarded",
                _merge_validation,
            ),
        ),
        compact_cases=_merge_cases,
        strong_cases=_merge_cases
        + (
            TestCase("Unsorted input", ([[5, 8], [1, 3]],), [[1, 3], [5, 8]]),
            TestCase("Touching boundaries", ([[1, 3], [3, 5]],), [[1, 5]]),
            TestCase("Containing interval", ([[1, 10], [2, 3]],), [[1, 10]]),
            TestCase("Reversed interval rejected", ([[5, 2]],), raises=ValueError),
        ),
    ),
}

EXERCISES.update(EXTRA_EXERCISES)
