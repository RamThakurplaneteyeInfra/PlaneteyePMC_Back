"""
Contract Value KPI calculations — computed at read time, never stored in DB.

revised_value = original_contract_value + excess_value - saving
increase_percentage = ((revised_value - original_contract_value) / original_contract_value) * 100
"""

from decimal import Decimal


def _to_decimal(value) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def compute_revised_value(
    original: Decimal | float | int,
    excess: Decimal | float | int,
    saving: Decimal | float | int,
) -> Decimal:
    return _to_decimal(original) + _to_decimal(excess) - _to_decimal(saving)


def compute_increase_percentage(
    original: Decimal | float | int,
    revised: Decimal | float | int,
) -> Decimal:
    original = _to_decimal(original)
    if original == 0:
        return Decimal("0.00")
    revised = _to_decimal(revised)
    return round(((revised - original) / original) * Decimal("100"), 2)


def metrics_from_amounts(
    original: Decimal | float | int,
    excess: Decimal | float | int,
    saving: Decimal | float | int,
) -> dict:
    original_d = _to_decimal(original)
    excess_d = _to_decimal(excess)
    saving_d = _to_decimal(saving)
    revised = compute_revised_value(original_d, excess_d, saving_d)
    increase = compute_increase_percentage(original_d, revised)
    return {
        "original_contract_value": original_d,
        "excess_value": excess_d,
        "saving": saving_d,
        "revised_value": revised,
        "increase_percentage": increase,
    }


def metrics_from_record(record) -> dict:
    if record is None:
        return metrics_from_amounts(0, 0, 0)
    return metrics_from_amounts(
        record.original_contract_value,
        record.excess_value,
        record.saving,
    )
