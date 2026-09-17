"""Shared pending calculation for correspondence KPI blocks."""

from decimal import Decimal


def compute_pending(
    received: int | None,
    delivered: int | None,
    record: int | None = 0,
) -> int:
    """Pending = max(received - delivered - record, 0)."""
    return max(
        int(received or 0) - int(delivered or 0) - int(record or 0),
        0,
    )
