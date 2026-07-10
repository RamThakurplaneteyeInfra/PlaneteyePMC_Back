"""Planned vs Actual KPI helpers — contractor summary computed at read time."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

TWO_PLACES = Decimal("0.01")
ZERO = Decimal("0")


def _as_decimal(value) -> Decimal:
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _pct(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator == 0:
        return ZERO
    return ((numerator / denominator) * Decimal("100")).quantize(
        TWO_PLACES, rounding=ROUND_HALF_UP
    )


def metrics_from_amounts(planned, actual, collection) -> dict:
    planned_d = _as_decimal(planned)
    actual_d = _as_decimal(actual)
    collection_d = _as_decimal(collection)
    difference = (planned_d - actual_d).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    return {
        "planned_value": planned_d,
        "actual_value": actual_d,
        "collection": collection_d,
        "difference": difference,
        "achievement_percentage": _pct(actual_d, planned_d),
        "collection_percentage": _pct(collection_d, actual_d),
        "variance_percentage": _pct(difference, planned_d),
    }


def empty_summary() -> dict:
    return metrics_from_amounts(0, 0, 0)


def contractor_summary_from_records(records) -> dict:
    """Sum contractor amounts, then recompute percentages from totals."""
    total_planned = ZERO
    total_actual = ZERO
    total_collection = ZERO
    for record in records:
        total_planned += _as_decimal(record.planned_value)
        total_actual += _as_decimal(record.actual_value)
        total_collection += _as_decimal(record.collection)
    return metrics_from_amounts(total_planned, total_actual, total_collection)


def summary_to_api(summary: dict) -> dict:
    """Serialize Decimal summary values as floats for JSON responses."""
    return {
        "planned_value": float(summary["planned_value"]),
        "actual_value": float(summary["actual_value"]),
        "collection": float(summary["collection"]),
        "difference": float(summary["difference"]),
        "achievement_percentage": float(summary["achievement_percentage"]),
        "collection_percentage": float(summary["collection_percentage"]),
        "variance_percentage": float(summary["variance_percentage"]),
    }
