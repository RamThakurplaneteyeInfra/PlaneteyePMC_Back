"""
Configurable thresholds for Project Overview KPI / project_status cards.

Override via Django settings or environment without changing formulas.
"""

from __future__ import annotations

from django.conf import settings


def _int_setting(name: str, default: int) -> int:
    try:
        return int(getattr(settings, name, default))
    except (TypeError, ValueError):
        return default


def _float_setting(name: str, default: float) -> float:
    try:
        return float(getattr(settings, name, default))
    except (TypeError, ValueError):
        return default


# Days until latest completion date → At Risk (approaching deadline)
AT_RISK_DAYS = _int_setting("OVERVIEW_AT_RISK_DAYS", 30)

# Calendar days past latest completion → Critical
CRITICAL_DELAY_DAYS = _int_setting("OVERVIEW_CRITICAL_DELAY_DAYS", 15)

# Minor overrun past latest completion → Watch (1 .. CRITICAL inclusive band start)
WATCH_DELAY_DAYS = _int_setting("OVERVIEW_WATCH_DELAY_DAYS", 15)

# Weighted health score (must sum ~1.0)
HEALTH_SCORE_WEIGHTS = {
    "progress": _float_setting("OVERVIEW_WEIGHT_PROGRESS", 0.25),
    "time": _float_setting("OVERVIEW_WEIGHT_TIME", 0.25),
    "quality": _float_setting("OVERVIEW_WEIGHT_QUALITY", 0.20),
    "safety": _float_setting("OVERVIEW_WEIGHT_SAFETY", 0.20),
    "cost": _float_setting("OVERVIEW_WEIGHT_COST", 0.10),
}

# Project status labels (additive card field)
STATUS_ON_TRACK = "On Track"
STATUS_WATCH = "Watch"
STATUS_AT_RISK = "At Risk"
STATUS_CRITICAL = "Critical"
STATUS_COMPLETED = "Completed"
STATUS_NO_DATA = "No Data"
