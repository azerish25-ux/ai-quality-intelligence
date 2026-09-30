"""Finite, versioned performance arithmetic and inert numeric projections."""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable
from fractions import Fraction
from typing import Any

ARITHMETIC_VERSION = "performance-arithmetic-v2"
NUMERIC_UNAVAILABLE = "NUMERIC_UNAVAILABLE"
NUMERIC_REASON = "performance_numeric_unavailable"
NUMERIC_SUMMARY = "Stored performance arithmetic is unavailable; review or recompute from the original measurements."


class PerformanceNumericError(ValueError):
    def __init__(self) -> None:
        super().__init__("performance arithmetic cannot produce finite results")


def is_finite(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def ratio(value: float) -> Fraction:
    if not is_finite(value):
        raise PerformanceNumericError()
    return Fraction(value)


def finite_result(value: Fraction) -> float:
    try:
        result = float(value)
    except OverflowError:
        raise PerformanceNumericError() from None
    if not math.isfinite(result):
        raise PerformanceNumericError()
    return result


def finite_median(values: Iterable[float]) -> float:
    ordered = sorted(values)
    if not ordered or not all(is_finite(value) for value in ordered):
        raise PerformanceNumericError()
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    # mean uses exact integer ratios, preserving subnormals as well as maxima.
    return statistics.mean((ordered[middle - 1], ordered[middle]))


def finite_mad(values: Iterable[float], center: float) -> float:
    center_ratio = ratio(center)
    deviations = sorted(abs(ratio(value) - center_ratio) for value in values)
    if not deviations:
        raise PerformanceNumericError()
    middle = len(deviations) // 2
    result = deviations[middle]
    if len(deviations) % 2 == 0:
        result = (deviations[middle - 1] + result) / 2
    return finite_result(result)


def metadata_is_finite(value: Any) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(metadata_is_finite(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return all(metadata_is_finite(item) for item in value)
    return True


def numeric_metadata(value: Any) -> Any:
    """Replace unavailable numbers only alongside an explicit validity state."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: numeric_metadata(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [numeric_metadata(item) for item in value]
    return value


def numeric_value(value: float | None) -> float | None:
    return value if is_finite(value) else None


def numeric_uncertainty(value: dict[str, Any], valid: bool) -> dict[str, Any]:
    return (
        numeric_metadata(value)
        if valid
        else {
            "numeric_state": "unavailable",
            "reason": NUMERIC_REASON,
            "significance_claimed": False,
        }
    )
