"""Seventeen original pure functions and four deliberate defects per function.

Functions are deliberately small and self-contained so the same source can be
placed in an isolated container without importing host application code.
"""

from __future__ import annotations


def parse_bool(text: str) -> bool:
    """Accept true/yes/1 or false/no/0, ignoring surrounding space and case."""
    value = text.strip().lower()
    if value in ("true", "yes", "1"):
        return True
    if value in ("false", "no", "0"):
        return False
    raise ValueError("unrecognized boolean")


def _bool_truthiness(text: str) -> bool:
    """Seed: confuse a nonempty string with a true value."""
    return bool(text)


def _bool_space(text: str) -> bool:
    """Seed: reject surrounding whitespace."""
    if text != text.strip():
        raise ValueError("whitespace")
    return parse_bool(text)


def _bool_case(text: str) -> bool:
    """Seed: reject uppercase characters."""
    if text != text.lower():
        raise ValueError("case")
    return parse_bool(text)


def _bool_unknown(text: str) -> bool:
    """Seed: silently interpret an unknown value as false."""
    try:
        return parse_bool(text)
    except ValueError:
        return False


def valid_identifier(name: str) -> bool:
    """Recognize non-keyword ASCII Python identifiers, including underscores."""
    import keyword

    return name.isascii() and name.isidentifier() and not keyword.iskeyword(name)


def _identifier_digit(name: str) -> bool:
    """Seed: accept a leading digit."""
    return True if name[:1].isdigit() else valid_identifier(name)


def _identifier_dash(name: str) -> bool:
    """Seed: accept a hyphen in an otherwise nonempty identifier."""
    return True if "-" in name else valid_identifier(name)


def _identifier_keyword(name: str) -> bool:
    """Seed: accept Python keywords."""
    return name.isascii() and name.isidentifier()


def _identifier_unicode(name: str) -> bool:
    """Seed: omit the ASCII requirement."""
    import keyword

    return name.isidentifier() and not keyword.iskeyword(name)


def normalize_hex(color: str) -> str:
    """Expand #RGB or normalize #RRGGBB to lowercase; reject other forms."""
    if not color.startswith("#") or len(color) not in (4, 7):
        raise ValueError("expected #RGB or #RRGGBB")
    raw = color[1:].lower()
    if any(character not in "0123456789abcdef" for character in raw):
        raise ValueError("invalid hex digit")
    return "#" + ("".join(character * 2 for character in raw) if len(raw) == 3 else raw)


def _hex_short(color: str) -> str:
    """Seed: fail to expand shorthand."""
    normalize_hex(color)
    return color.lower()


def _hex_case(color: str) -> str:
    """Seed: return uppercase output."""
    return normalize_hex(color).upper()


def _hex_prefix(color: str) -> str:
    """Seed: accept a missing # prefix."""
    return normalize_hex(color if color.startswith("#") else "#" + color)


def _hex_digits(color: str) -> str:
    """Seed: accept non-hex digits."""
    if color.startswith("#") and len(color) in (4, 7):
        raw = color[1:].lower()
        return "#" + ("".join(c * 2 for c in raw) if len(raw) == 3 else raw)
    return normalize_hex(color)


def ceil_div(numerator: int, denominator: int) -> int:
    """Ceiling division for a nonnegative numerator and positive denominator."""
    if numerator < 0 or denominator <= 0:
        raise ValueError("invalid operands")
    return (numerator + denominator - 1) // denominator


def _ceil_floor(numerator: int, denominator: int) -> int:
    """Seed: use floor division."""
    ceil_div(numerator, denominator)
    return numerator // denominator


def _ceil_exact(numerator: int, denominator: int) -> int:
    """Seed: add one even when exactly divisible."""
    value = ceil_div(numerator, denominator)
    return value + int(numerator % denominator == 0)


def _ceil_zero(numerator: int, denominator: int) -> int:
    """Seed: return one for a zero numerator."""
    return 1 if numerator == 0 else ceil_div(numerator, denominator)


def _ceil_validation(numerator: int, denominator: int) -> int:
    """Seed: omit operand validation."""
    return (numerator + denominator - 1) // denominator


def shipping_cost(weight_grams: int, subtotal_cents: int) -> int:
    """Charge 500/1200/2000 cents at <=1000/<=5000/>5000 g; free at subtotal >=5000."""
    if weight_grams <= 0 or subtotal_cents < 0:
        raise ValueError("invalid order")
    if subtotal_cents >= 5000:
        return 0
    if weight_grams <= 1000:
        return 500
    return 1200 if weight_grams <= 5000 else 2000


def _shipping_first(weight_grams: int, subtotal_cents: int) -> int:
    """Seed: exclude the first weight boundary."""
    return (
        1200
        if weight_grams == 1000 and subtotal_cents < 5000
        else shipping_cost(weight_grams, subtotal_cents)
    )


def _shipping_second(weight_grams: int, subtotal_cents: int) -> int:
    """Seed: exclude the second weight boundary."""
    return (
        2000
        if weight_grams == 5000 and subtotal_cents < 5000
        else shipping_cost(weight_grams, subtotal_cents)
    )


def _shipping_free(weight_grams: int, subtotal_cents: int) -> int:
    """Seed: exclude the free-shipping subtotal boundary."""
    return shipping_cost(
        weight_grams, 4999 if subtotal_cents == 5000 else subtotal_cents
    )


def _shipping_validation(weight_grams: int, subtotal_cents: int) -> int:
    """Seed: accept nonpositive weights and negative subtotals."""
    return (
        500
        if weight_grams <= 0 or subtotal_cents < 0
        else shipping_cost(weight_grams, subtotal_cents)
    )


def weighted_average(values: list[float], weights: list[float]) -> float:
    """Return a weighted mean; require equal nonempty lengths and nonnegative weights with positive total."""
    if (
        not values
        or len(values) != len(weights)
        or any(weight < 0 for weight in weights)
        or sum(weights) <= 0
    ):
        raise ValueError("invalid weights")
    return sum(
        value * weight for value, weight in zip(values, weights, strict=True)
    ) / sum(weights)


def _weighted_ignored(values: list[float], weights: list[float]) -> float:
    """Seed: compute an unweighted mean."""
    weighted_average(values, weights)
    return sum(values) / len(values)


def _weighted_truncate(values: list[float], weights: list[float]) -> float:
    """Seed: truncate the result to a whole number."""
    return float(int(weighted_average(values, weights)))


def _weighted_zero(values: list[float], weights: list[float]) -> float:
    """Seed: accept zero total weight."""
    return 0.0 if sum(weights) == 0 else weighted_average(values, weights)


def _weighted_lengths(values: list[float], weights: list[float]) -> float:
    """Seed: silently truncate unequal inputs."""
    if len(values) != len(weights) and sum(weights) > 0:
        return sum(v * w for v, w in zip(values, weights, strict=False)) / sum(weights)
    return weighted_average(values, weights)


def stable_unique(values: list[int]) -> list[int]:
    """Remove duplicate integers while preserving first-occurrence order."""
    result: list[int] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _unique_sorted(values: list[int]) -> list[int]:
    """Seed: sort the output."""
    return sorted(stable_unique(values))


def _unique_zero(values: list[int]) -> list[int]:
    """Seed: discard zero values."""
    return stable_unique([value for value in values if value != 0])


def _unique_last(values: list[int]) -> list[int]:
    """Seed: preserve last-occurrence order."""
    return list(reversed(stable_unique(list(reversed(values)))))


def _unique_duplicates(values: list[int]) -> list[int]:
    """Seed: leave duplicate values untouched."""
    return list(values)


def chunks(values: list[int], size: int) -> list[list[int]]:
    """Split into consecutive chunks, preserving a short final chunk; require size >0."""
    if size <= 0:
        raise ValueError("size must be positive")
    return [values[index : index + size] for index in range(0, len(values), size)]


def _chunks_remainder(values: list[int], size: int) -> list[list[int]]:
    """Seed: drop the final incomplete chunk."""
    return [part for part in chunks(values, size) if len(part) == size]


def _chunks_first(values: list[int], size: int) -> list[list[int]]:
    """Seed: skip the first item."""
    return chunks(values[1:], size)


def _chunks_overlap(values: list[int], size: int) -> list[list[int]]:
    """Seed: overlap neighboring chunks."""
    chunks(values, size)
    return [
        values[index : index + size]
        for index in range(0, len(values), max(1, size - 1))
    ]


def _chunks_validation(values: list[int], size: int) -> list[list[int]]:
    """Seed: silently accept invalid chunk sizes."""
    return [] if size <= 0 else chunks(values, size)


def rotate(values: list[int], steps: int) -> list[int]:
    """Rotate right by steps (negative rotates left), using modulo length; empty stays empty."""
    if not values:
        return []
    offset = steps % len(values)
    return values[-offset:] + values[:-offset] if offset else list(values)


def _rotate_direction(values: list[int], steps: int) -> list[int]:
    """Seed: rotate in the opposite direction."""
    return rotate(values, -steps)


def _rotate_modulo(values: list[int], steps: int) -> list[int]:
    """Seed: omit modulo for oversized steps."""
    return values[-steps:] + values[:-steps] if steps else list(values)


def _rotate_negative(values: list[int], steps: int) -> list[int]:
    """Seed: discard the sign of steps."""
    return rotate(values, abs(steps))


def _rotate_empty(values: list[int], steps: int) -> list[int]:
    """Seed: divide by zero for empty input."""
    steps %= len(values)
    return rotate(values, steps)


def top_k(values: list[int], k: int) -> list[int]:
    """Return up to k integers descending, retaining duplicates; reject negative k."""
    if k < 0:
        raise ValueError("k must be nonnegative")
    return sorted(values, reverse=True)[:k]


def _top_ascending(values: list[int], k: int) -> list[int]:
    """Seed: select the smallest items."""
    top_k(values, k)
    return sorted(values)[:k]


def _top_duplicates(values: list[int], k: int) -> list[int]:
    """Seed: discard duplicate values."""
    return top_k(list(set(values)), k)


def _top_zero(values: list[int], k: int) -> list[int]:
    """Seed: return everything for k=0."""
    return sorted(values, reverse=True) if k == 0 else top_k(values, k)


def _top_validation(values: list[int], k: int) -> list[int]:
    """Seed: accept negative k as a Python slice."""
    return sorted(values, reverse=True)[:k]


def slugify(text: str) -> str:
    """Lowercase ASCII letters/digits; replace separator runs with one hyphen and trim."""
    import re

    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _slug_case(text: str) -> str:
    """Seed: uppercase the result."""
    return slugify(text).upper()


def _slug_underscore(text: str) -> str:
    """Seed: retain underscores."""
    import re

    return re.sub(r"[^a-z0-9_]+", "-", text.lower()).strip("-")


def _slug_edges(text: str) -> str:
    """Seed: omit trimming separators."""
    import re

    return re.sub(r"[^a-z0-9]+", "-", text.lower())


def _slug_unicode(text: str) -> str:
    """Seed: retain Unicode letters."""
    import re

    return re.sub(r"[^\w]+", "-", text.lower()).strip("-")


def truncate(text: str, maximum: int) -> str:
    """Limit total length, using ... when shortened or dots only for limits <=3; reject negative limits."""
    if maximum < 0:
        raise ValueError("negative limit")
    if len(text) <= maximum:
        return text
    return "." * maximum if maximum <= 3 else text[: maximum - 3] + "..."


def _truncate_length(text: str, maximum: int) -> str:
    """Seed: exceed the total length by one."""
    result = truncate(text, maximum)
    return text[: maximum - 2] + "..." if len(text) > maximum > 3 else result


def _truncate_exact(text: str, maximum: int) -> str:
    """Seed: shorten text that exactly meets the limit."""
    result = truncate(text, maximum)
    return (
        text[: maximum - 3] + "..." if len(text) == maximum and maximum > 3 else result
    )


def _truncate_small(text: str, maximum: int) -> str:
    """Seed: always use three dots for tiny limits."""
    result = truncate(text, maximum)
    return "..." if len(text) > maximum and maximum < 3 else result


def _truncate_validation(text: str, maximum: int) -> str:
    """Seed: accept a negative limit."""
    return "" if maximum < 0 else truncate(text, maximum)


def mask_email(email: str) -> str:
    """Require one @ and nonempty local/domain; preserve the first local character and full domain."""
    if email.count("@") != 1:
        raise ValueError("expected one @")
    local, domain = email.split("@")
    if not local or not domain:
        raise ValueError("empty local or domain")
    return local[0] + "*" * (len(local) - 1) + "@" + domain


def _email_reveal(email: str) -> str:
    """Seed: expose a second local character."""
    mask_email(email)
    local, domain = email.split("@")
    return local[:2] + "*" * max(0, len(local) - 2) + "@" + domain


def _email_domain(email: str) -> str:
    """Seed: mask the domain too."""
    return mask_email(email).split("@")[0] + "@***"


def _email_single(email: str) -> str:
    """Seed: mask the only local character."""
    result = mask_email(email)
    return "*" + result[1:] if email.index("@") == 1 else result


def _email_validation(email: str) -> str:
    """Seed: accept malformed addresses."""
    local, _, domain = email.partition("@")
    return local[:1] + "*" * max(0, len(local) - 1) + "@" + domain


def collapse_whitespace(text: str) -> str:
    """Collapse all whitespace runs to one ASCII space and trim both ends."""
    return " ".join(text.split())


def _whitespace_spaces(text: str) -> str:
    """Seed: split only on ordinary spaces."""
    return " ".join(piece for piece in text.split(" ") if piece)


def _whitespace_edges(text: str) -> str:
    """Seed: fail to trim outer whitespace."""
    import re

    return re.sub(r"\s+", " ", text)


def _whitespace_remove(text: str) -> str:
    """Seed: remove separators entirely."""
    return "".join(text.split())


def _whitespace_newlines(text: str) -> str:
    """Seed: leave line breaks untouched."""
    import re

    return re.sub(r"[ \t]+", " ", text.strip())


def overlaps(first: list[int], second: list[int]) -> bool:
    """Check inclusive intersection of two closed intervals; require two ordered endpoints each."""
    if (
        len(first) != 2
        or len(second) != 2
        or first[0] > first[1]
        or second[0] > second[1]
    ):
        raise ValueError("invalid interval")
    return max(first[0], second[0]) <= min(first[1], second[1])


def _overlap_touching(first: list[int], second: list[int]) -> bool:
    """Seed: treat touching endpoints as disjoint."""
    overlaps(first, second)
    return max(first[0], second[0]) < min(first[1], second[1])


def _overlap_one_sided(first: list[int], second: list[int]) -> bool:
    """Seed: check only one side of intersection."""
    overlaps(first, second)
    return first[0] <= second[1]


def _overlap_containment(first: list[int], second: list[int]) -> bool:
    """Seed: require the second interval to start inside the first."""
    overlaps(first, second)
    return first[0] <= second[0] <= first[1]


def _overlap_validation(first: list[int], second: list[int]) -> bool:
    """Seed: omit endpoint validation."""
    return max(first[0], second[0]) <= min(first[1], second[1])


def interval_gaps(intervals: list[list[int]]) -> list[list[int]]:
    """Return closed integer gaps between sorted/merged intervals; reject reversed pairs."""
    if any(len(pair) != 2 or pair[0] > pair[1] for pair in intervals):
        raise ValueError("invalid interval")
    merged: list[list[int]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [
        [left[1] + 1, right[0] - 1]
        for left, right in zip(merged, merged[1:], strict=False)
    ]


def _gaps_endpoints(intervals: list[list[int]]) -> list[list[int]]:
    """Seed: include occupied endpoints in each gap."""
    return [[start - 1, end + 1] for start, end in interval_gaps(intervals)]


def _gaps_sorting(intervals: list[list[int]]) -> list[list[int]]:
    """Seed: assume supplied intervals are sorted and disjoint."""
    interval_gaps(intervals)
    return [
        [left[1] + 1, right[0] - 1]
        for left, right in zip(intervals, intervals[1:], strict=False)
        if left[1] + 1 < right[0]
    ]


def _gaps_adjacent(intervals: list[list[int]]) -> list[list[int]]:
    """Seed: report an invalid gap between adjacent intervals."""
    result = interval_gaps(intervals)
    for left, right in zip(intervals, intervals[1:], strict=False):
        if left[1] + 1 == right[0]:
            result.append([left[1] + 1, right[0] - 1])
    return result


def _gaps_empty(intervals: list[list[int]]) -> list[list[int]]:
    """Seed: reject valid empty input."""
    if not intervals:
        raise ValueError("empty")
    return interval_gaps(intervals)


def inclusive_range(start: int, stop: int, step: int) -> list[int]:
    """Integer range with an included stop when reachable; support either step sign and reject zero."""
    if step == 0:
        raise ValueError("step must not be zero")
    return list(range(start, stop + (1 if step > 0 else -1), step))


def _range_stop(start: int, stop: int, step: int) -> list[int]:
    """Seed: exclude a reachable stop."""
    inclusive_range(start, stop, step)
    return list(range(start, stop, step))


def _range_negative(start: int, stop: int, step: int) -> list[int]:
    """Seed: adjust a descending stop in the wrong direction."""
    inclusive_range(start, stop, step)
    return list(range(start, stop + 1, step))


def _range_zero(start: int, stop: int, step: int) -> list[int]:
    """Seed: silently accept a zero step."""
    return [] if step == 0 else inclusive_range(start, stop, step)


def _range_order(start: int, stop: int, step: int) -> list[int]:
    """Seed: reverse descending output into ascending order."""
    result = inclusive_range(start, stop, step)
    return sorted(result)
