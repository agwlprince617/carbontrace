"""Original cases for seventeen functions; holdout access is excluded from the UI."""

from __future__ import annotations

from carbontrace import extra_functions as f
from carbontrace.exercise import Exercise, Mutation, Split, Target
from carbontrace.exercise import TestCase as Case


def item(
    target: Target,
    category: str,
    faults: tuple[Target, ...],
    cases: tuple[Case, ...],
    split: Split = "development",
) -> Exercise:
    """Build explicit fixtures; these profiles do not represent real models."""
    return Exercise(
        id=target.__name__,
        title=target.__name__.replace("_", " ").capitalize(),
        category=category,
        description=target.__doc__ or "",
        function=target,
        mutations=tuple(
            Mutation(fault.__name__.lstrip("_"), fault.__doc__ or "", fault)
            for fault in faults
        ),
        compact_cases=cases[:2],
        strong_cases=cases,
        split=split,
    )


_items = (
    item(
        f.parse_bool,
        "Validation",
        (f._bool_truthiness, f._bool_space, f._bool_case, f._bool_unknown),
        (
            Case("True", ("true",), True),
            Case("False", ("false",), False),
            Case("Spaces and case", (" YES ",), True),
            Case("Mixed case", ("No",), False),
            Case("Zero", ("0",), False),
            Case("Unknown", ("unknown",), raises=ValueError),
        ),
    ),
    item(
        f.valid_identifier,
        "Validation",
        (
            f._identifier_digit,
            f._identifier_dash,
            f._identifier_keyword,
            f._identifier_unicode,
        ),
        (
            Case("Valid", ("item_2",), True),
            Case("Underscore", ("_x",), True),
            Case("Leading digit", ("2item",), False),
            Case("Hyphen", ("my-item",), False),
            Case("Keyword", ("class",), False),
            Case("Unicode", ("é",), False),
            Case("Empty", ("",), False),
        ),
    ),
    item(
        f.normalize_hex,
        "Validation",
        (f._hex_short, f._hex_case, f._hex_prefix, f._hex_digits),
        (
            Case("Shorthand", ("#ABC",), "#aabbcc"),
            Case("Full", ("#A0b1C2",), "#a0b1c2"),
            Case("Missing prefix", ("abc",), raises=ValueError),
            Case("Bad length", ("#abcd",), raises=ValueError),
            Case("Bad digits", ("#ggg",), raises=ValueError),
        ),
        "holdout",
    ),
    item(
        f.ceil_div,
        "Arithmetic",
        (f._ceil_floor, f._ceil_exact, f._ceil_zero, f._ceil_validation),
        (
            Case("Remainder", (7, 3), 3),
            Case("Exact", (6, 3), 2),
            Case("Zero", (0, 3), 0),
            Case("Negative", (-1, 3), raises=ValueError),
            Case("Zero denominator", (1, 0), raises=ValueError),
        ),
    ),
    item(
        f.shipping_cost,
        "Arithmetic",
        (
            f._shipping_first,
            f._shipping_second,
            f._shipping_free,
            f._shipping_validation,
        ),
        (
            Case("Light", (500, 100), 500),
            Case("First boundary", (1000, 100), 500),
            Case("Second boundary", (5000, 100), 1200),
            Case("Heavy", (5001, 100), 2000),
            Case("Free boundary", (100, 5000), 0),
            Case("Zero weight", (0, 100), raises=ValueError),
            Case("Negative subtotal", (100, -1), raises=ValueError),
        ),
    ),
    item(
        f.weighted_average,
        "Arithmetic",
        (
            f._weighted_ignored,
            f._weighted_truncate,
            f._weighted_zero,
            f._weighted_lengths,
        ),
        (
            Case("Unequal weights", ([10.0, 20.0], [1.0, 3.0]), 17.5),
            Case("Fraction", ([1.0, 2.0], [1.0, 1.0]), 1.5),
            Case("Zero total", ([1.0], [0.0]), raises=ValueError),
            Case("Unequal lengths", ([1.0, 2.0], [1.0]), raises=ValueError),
            Case("Negative weight", ([1.0, 2.0], [-1.0, 2.0]), raises=ValueError),
            Case("Empty", ([], []), raises=ValueError),
        ),
        "holdout",
    ),
    item(
        f.stable_unique,
        "Collections",
        (f._unique_sorted, f._unique_zero, f._unique_last, f._unique_duplicates),
        (
            Case("Order", ([3, 1, 3, 2],), [3, 1, 2]),
            Case("Zero", ([0, 1, 0],), [0, 1]),
            Case("First occurrence", ([2, 1, 2],), [2, 1]),
            Case("Empty", ([],), []),
            Case("Duplicates", ([4, 4],), [4]),
        ),
    ),
    item(
        f.chunks,
        "Collections",
        (f._chunks_remainder, f._chunks_first, f._chunks_overlap, f._chunks_validation),
        (
            Case("Remainder", ([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]]),
            Case("Size one", ([1, 2, 3], 1), [[1], [2], [3]]),
            Case("Empty", ([], 2), []),
            Case("Zero size", ([1], 0), raises=ValueError),
            Case("Negative size", ([1], -1), raises=ValueError),
        ),
    ),
    item(
        f.rotate,
        "Collections",
        (f._rotate_direction, f._rotate_modulo, f._rotate_negative, f._rotate_empty),
        (
            Case("Right", ([1, 2, 3, 4], 1), [4, 1, 2, 3]),
            Case("Modulo", ([1, 2, 3, 4], 5), [4, 1, 2, 3]),
            Case("Left", ([1, 2, 3, 4], -1), [2, 3, 4, 1]),
            Case("Empty", ([], 10), []),
            Case("Zero", ([1, 2], 0), [1, 2]),
        ),
        "holdout",
    ),
    item(
        f.top_k,
        "Collections",
        (f._top_ascending, f._top_duplicates, f._top_zero, f._top_validation),
        (
            Case("Duplicates", ([2, 5, 5, 1], 3), [5, 5, 2]),
            Case("Zero", ([1, 2], 0), []),
            Case("Negative", ([1, 2], -1), raises=ValueError),
            Case("Empty", ([], 2), []),
            Case("Oversized", ([1, 2], 5), [2, 1]),
        ),
    ),
    item(
        f.slugify,
        "Strings",
        (f._slug_case, f._slug_underscore, f._slug_edges, f._slug_unicode),
        (
            Case("Case and punctuation", (" Hello, WORLD! ",), "hello-world"),
            Case("Underscore", ("a__b",), "a-b"),
            Case("Outer hyphens", ("---hello---",), "hello"),
            Case("ASCII only", ("café",), "caf"),
            Case("Empty", ("",), ""),
            Case("Punctuation", ("!!!",), ""),
        ),
    ),
    item(
        f.truncate,
        "Strings",
        (
            f._truncate_length,
            f._truncate_exact,
            f._truncate_small,
            f._truncate_validation,
        ),
        (
            Case("Shortened", ("abcdef", 5), "ab..."),
            Case("Exact", ("abcde", 5), "abcde"),
            Case("Tiny limit", ("abcdef", 2), ".."),
            Case("Negative", ("abc", -1), raises=ValueError),
            Case("Empty", ("", 0), ""),
            Case("Three", ("abcd", 3), "..."),
        ),
    ),
    item(
        f.mask_email,
        "Strings",
        (f._email_reveal, f._email_domain, f._email_single, f._email_validation),
        (
            Case("Long local", ("alice@example.com",), "a****@example.com"),
            Case("Single local", ("x@domain.io",), "x@domain.io"),
            Case("Missing @", ("invalid",), raises=ValueError),
            Case("Repeated @", ("a@@b",), raises=ValueError),
            Case("Empty local", ("@b",), raises=ValueError),
            Case("Empty domain", ("a@",), raises=ValueError),
        ),
        "holdout",
    ),
    item(
        f.collapse_whitespace,
        "Strings",
        (
            f._whitespace_spaces,
            f._whitespace_edges,
            f._whitespace_remove,
            f._whitespace_newlines,
        ),
        (
            Case("Spaces", ("  a  b  ",), "a b"),
            Case("All whitespace", ("a\n\tb",), "a b"),
            Case("Empty", ("",), ""),
            Case("Whitespace only", (" \t\n",), ""),
            Case("Single", ("a",), "a"),
        ),
    ),
    item(
        f.overlaps,
        "Intervals",
        (
            f._overlap_touching,
            f._overlap_one_sided,
            f._overlap_containment,
            f._overlap_validation,
        ),
        (
            Case("Touching", ([1, 3], [3, 5]), True),
            Case("Disjoint", ([1, 2], [5, 7]), False),
            Case("Containment", ([3, 4], [1, 6]), True),
            Case("Reversed", ([3, 1], [2, 4]), raises=ValueError),
            Case("Bad length", ([1], [2, 4]), raises=ValueError),
        ),
        "holdout",
    ),
    item(
        f.interval_gaps,
        "Intervals",
        (f._gaps_endpoints, f._gaps_sorting, f._gaps_adjacent, f._gaps_empty),
        (
            Case("Gap", ([[1, 2], [5, 6]],), [[3, 4]]),
            Case("Unsorted", ([[5, 6], [1, 2]],), [[3, 4]]),
            Case("Adjacent", ([[1, 2], [3, 4]],), []),
            Case("Empty", ([],), []),
            Case("Nested", ([[1, 5], [2, 3], [8, 9]],), [[6, 7]]),
            Case("Reversed", ([[3, 1]],), raises=ValueError),
        ),
        "holdout",
    ),
    item(
        f.inclusive_range,
        "Intervals",
        (f._range_stop, f._range_negative, f._range_zero, f._range_order),
        (
            Case("Ascending", (1, 5, 2), [1, 3, 5]),
            Case("Descending", (5, 1, -2), [5, 3, 1]),
            Case("Wrong direction", (1, 3, -1), []),
            Case("Same start stop", (2, 2, 1), [2]),
            Case("Same descending", (2, 2, -1), [2]),
            Case("Zero step", (1, 3, 0), raises=ValueError),
        ),
    ),
)

EXTRA_EXERCISES = {exercise.id: exercise for exercise in _items}
