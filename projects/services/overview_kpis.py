"""
Card KPI helpers for Project Overview.

Reuses existing domain formulas — does not invent new calculation logic.
Maps domain statuses onto the dashboard card labels: Excellent / Watch / Delay.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Any

from health_safety.services import (
    HealthSafetyInput,
    calculate_severity_index,
    calculate_severity_score,
    determine_safety_status,
)
from project_quality_status.controllers.quality_metrics import (
    compute_quality_performance,
    quality_status_from_performance,
)

# Dashboard card badge labels (frontend contract).
CARD_EXCELLENT = "Excellent"
CARD_WATCH = "Watch"
CARD_DELAY = "Delay"

_PROGRESS_STATUS_TO_CARD = {
    "on_track": CARD_EXCELLENT,
    "slight_delay": CARD_WATCH,
    "delayed": CARD_DELAY,
    "critical": CARD_DELAY,
}

_QUALITY_STATUS_TO_CARD = {
    "excellent": CARD_EXCELLENT,
    "good": CARD_WATCH,
    "average": CARD_WATCH,
    "poor": CARD_DELAY,
}

_COST_STATUS_TO_CARD = {
    "under_budget": CARD_EXCELLENT,
    "on_budget": CARD_EXCELLENT,
    "over_budget": CARD_DELAY,
    "unknown": CARD_WATCH,
}

_SAFETY_STATUS_TO_CARD = {
    "safe": CARD_EXCELLENT,
    "moderate": CARD_WATCH,
    "high_risk": CARD_DELAY,
    "critical": CARD_DELAY,
}

_LEADING_CODE_RE = re.compile(r"^([A-Za-z]?\d[\w.-]*)\s*[:\-]?\s+")
_PAREN_CODE_RE = re.compile(r"\(([A-Za-z]-?\d[\w.-]*)\)\s*$")


def extract_project_code(name: str | None) -> str:
    """Best-effort code from project name (e.g. B3482, A-3462)."""
    text = (name or "").strip()
    if not text:
        return ""
    leading = _LEADING_CODE_RE.match(text)
    if leading:
        return leading.group(1)
    paren = _PAREN_CODE_RE.search(text)
    if paren:
        return paren.group(1)
    return ""


def _pct_int(value: float | int | Decimal | None) -> int:
    if value is None:
        return 0
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0


def _clamp_pct(value: float | int | Decimal | None) -> int:
    return max(0, min(100, _pct_int(value)))


def progress_status_from_performance(performance_percentage: float) -> str:
    """
    Same bands as ConstructionProgress.progressStatus.
      >= 100 → on_track
      >= 80  → slight_delay
      >= 60  → delayed
      < 60   → critical
    """
    pct = float(performance_percentage or 0)
    if pct >= 100:
        return "on_track"
    if pct >= 80:
        return "slight_delay"
    if pct >= 60:
        return "delayed"
    return "critical"


def cost_status_from_cpi(cpi: float | Decimal | None) -> str:
    """Same bands as cost_performance dashboard EVM status."""
    if cpi is None:
        return "unknown"
    value = float(cpi)
    if value > 1:
        return "under_budget"
    if value == 1:
        return "on_budget"
    return "over_budget"


def build_progress_kpi(progress_row) -> dict[str, Any]:
    """Reuse ConstructionProgress actual + performanceStatus bands."""
    if progress_row is None:
        return {"percentage": 0, "status": CARD_WATCH}
    actual = getattr(progress_row, "actualProgress", 0) or 0
    performance = getattr(progress_row, "performancePercentage", None)
    if performance is None:
        planned = getattr(progress_row, "plannedProgress", 0) or 0
        performance = (actual / planned * 100) if planned else 0.0
    domain_status = progress_status_from_performance(performance)
    return {
        "percentage": _clamp_pct(actual),
        "status": _PROGRESS_STATUS_TO_CARD.get(domain_status, CARD_WATCH),
    }


def build_time_kpi(project, progress_percentage: int) -> dict[str, Any]:
    """
    Schedule elapsed % from existing project dates.
    Status uses Project.delay_days and progress-vs-time comparison.
    """
    start = (
        getattr(project, "project_start", None)
        or getattr(project, "start_date", None)
        or getattr(project, "commencement_date", None)
    )
    finish = getattr(project, "contract_finish", None) or getattr(project, "end_date", None)
    if not start or not finish:
        delay_days = getattr(project, "delay_days", 0) or 0
        if delay_days > 0:
            return {"percentage": 0, "status": CARD_DELAY}
        return {"percentage": 0, "status": CARD_WATCH}

    total_days = (finish - start).days
    if total_days <= 0:
        return {"percentage": 0, "status": CARD_WATCH}

    today = date.today()
    elapsed_days = (min(today, finish) - start).days
    percentage = _clamp_pct((elapsed_days / total_days) * 100)

    delay_days = getattr(project, "delay_days", 0) or 0
    if delay_days > 0:
        status = CARD_DELAY
    elif progress_percentage + 5 < percentage:
        status = CARD_DELAY
    elif progress_percentage >= percentage:
        status = CARD_EXCELLENT
    else:
        status = CARD_WATCH

    return {"percentage": percentage, "status": status}


def build_cost_kpi(cost_row) -> dict[str, Any]:
    """Reuse ProjectCostPerformance.cpi and EVM budget status bands."""
    if cost_row is None:
        return {"percentage": 0, "status": CARD_WATCH}
    cpi = getattr(cost_row, "cpi", None)
    domain_status = cost_status_from_cpi(cpi)
    percentage = _clamp_pct(float(cpi) * 100) if cpi is not None else 0
    # Mild over-budget still maps to Watch when CPI >= 0.7
    if domain_status == "over_budget" and percentage >= 70:
        card_status = CARD_WATCH
    else:
        card_status = _COST_STATUS_TO_CARD.get(domain_status, CARD_WATCH)
    return {"percentage": percentage, "status": card_status}


def build_quality_kpi(quality_row) -> dict[str, Any]:
    """Reuse compute_quality_performance + quality_status_from_performance."""
    if quality_row is None:
        return {"percentage": 0, "status": CARD_WATCH}
    pct = compute_quality_performance(
        getattr(quality_row, "tests_passed", 0),
        getattr(quality_row, "tests_conducted", 0),
    )
    domain_status = quality_status_from_performance(pct)
    return {
        "percentage": _clamp_pct(pct),
        "status": _QUALITY_STATUS_TO_CARD.get(domain_status, CARD_WATCH),
    }


def build_safety_kpi(hse_row) -> dict[str, Any]:
    """
    Reuse health_safety.services severity + determine_safety_status.
    Card percentage = 100 - severity_index (existing 0–100 index).
    """
    if hse_row is None:
        return {"percentage": 100, "status": CARD_EXCELLENT}

    input_data = HealthSafetyInput(
        total_manhours=float(getattr(hse_row, "totalManhours", 0) or 0),
        fatalities=int(getattr(hse_row, "fatalities", 0) or 0),
        significant=int(getattr(hse_row, "significant", 0) or 0),
        major=int(getattr(hse_row, "major", 0) or 0),
        minor=int(getattr(hse_row, "minor", 0) or 0),
        near_miss=int(getattr(hse_row, "nearMiss", 0) or 0),
    )
    total_incidents = input_data.total_incidents
    manhours = input_data.total_manhours
    incident_rate = (
        (total_incidents / manhours) * 1_000_000 if manhours > 0 else 0.0
    )
    domain_status = determine_safety_status(input_data, incident_rate)
    severity_score = calculate_severity_score(input_data)
    severity_index = calculate_severity_index(severity_score)
    percentage = _clamp_pct(100 - severity_index)
    return {
        "percentage": percentage,
        "status": _SAFETY_STATUS_TO_CARD.get(domain_status, CARD_WATCH),
    }


def compute_health_score(*kpi_percentages: int) -> int:
    """Average of card KPI percentages (progress/time/cost/quality/safety)."""
    values = [int(v) for v in kpi_percentages]
    if not values:
        return 0
    return int(round(sum(values) / len(values)))
