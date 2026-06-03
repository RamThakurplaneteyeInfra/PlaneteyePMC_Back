"""
Invoicing KPI calculations — computed at read time, never stored in DB.

difference = gross_billed - gross_certified_billed
certification_efficiency = (gross_certified_billed / gross_billed) * 100
"""

from decimal import Decimal


def _to_decimal(value) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def compute_difference(gross_billed, gross_certified_billed) -> Decimal:
    return _to_decimal(gross_billed) - _to_decimal(gross_certified_billed)


def compute_certification_efficiency(gross_billed, gross_certified_billed) -> Decimal:
    gross_billed = _to_decimal(gross_billed)
    if gross_billed == 0:
        return Decimal("0.00")
    certified = _to_decimal(gross_certified_billed)
    return round((certified / gross_billed) * Decimal("100"), 2)


def metrics_from_amounts(gross_billed, gross_certified_billed) -> dict:
    gross_billed_d = _to_decimal(gross_billed)
    certified_d = _to_decimal(gross_certified_billed)
    difference = compute_difference(gross_billed_d, certified_d)
    efficiency = compute_certification_efficiency(gross_billed_d, certified_d)
    return {
        "gross_billed": gross_billed_d,
        "gross_certified_billed": certified_d,
        "difference": difference,
        "certification_efficiency": efficiency,
    }


def metrics_from_record(record) -> dict:
    if record is None:
        return metrics_from_amounts(0, 0)
    return metrics_from_amounts(
        record.gross_billed,
        record.gross_certified_billed,
    )
