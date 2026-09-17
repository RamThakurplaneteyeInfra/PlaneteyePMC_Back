"""
Card KPI helpers for Project Overview.

Computes live KPIs from:
  - Progress: Assigned Scope cumulative (DPR) with ConstructionProgress fallback
  - Time / project_status: Contract finish + approved EOT + today
  - Cost: Cost Performance CPI
  - Quality: QAQC pass rate
  - Safety: HSE severity (never stub 100% when missing)
  - Health: configurable weighted average
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
from projects.overview_thresholds import (
    AT_RISK_DAYS,
    CRITICAL_DELAY_DAYS,
    HEALTH_SCORE_WEIGHTS,
    STATUS_AT_RISK,
    STATUS_COMPLETED,
    STATUS_CRITICAL,
    STATUS_NO_DATA,
    STATUS_ON_TRACK,
    STATUS_WATCH,
    WATCH_DELAY_DAYS,
)

# Dashboard card badge labels (frontend contract — keep Excellent/Watch/Delay).
CARD_EXCELLENT = "Excellent"
CARD_WATCH = "Watch"
CARD_DELAY = "Delay"
CARD_NO_DATA = STATUS_NO_DATA
CARD_ON_TRACK = STATUS_ON_TRACK
CARD_AT_RISK = STATUS_AT_RISK
CARD_CRITICAL = STATUS_CRITICAL

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
    pct = float(performance_percentage or 0)
    if pct >= 100:
        return "on_track"
    if pct >= 80:
        return "slight_delay"
    if pct >= 60:
        return "delayed"
    return "critical"


def cost_status_from_cpi(cpi: float | Decimal | None) -> str:
    if cpi is None:
        return "unknown"
    value = float(cpi)
    if value > 1:
        return "under_budget"
    if value == 1:
        return "on_budget"
    return "over_budget"


def build_progress_kpi(
    *,
    scope_pct: float | int | Decimal | None = None,
    progress_row=None,
) -> dict[str, Any]:
    """
    Prefer Assigned Scope cumulative progress; fall back to ConstructionProgress.
    """
    if scope_pct is not None:
        pct = _clamp_pct(scope_pct)
        domain = progress_status_from_performance(float(scope_pct))
        return {
            "percentage": pct,
            "status": _PROGRESS_STATUS_TO_CARD.get(domain, CARD_WATCH),
        }

    if progress_row is None:
        return {"percentage": 0, "status": CARD_NO_DATA}

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


def resolve_completion_date(
    project,
    *,
    latest_eot_date: date | None = None,
    contract_finish: date | None = None,
) -> date | None:
    """Latest approved EOT revised date, else contract finish / Project dates."""
    if latest_eot_date:
        return latest_eot_date
    if contract_finish:
        return contract_finish
    return (
        getattr(project, "contract_finish", None)
        or getattr(project, "end_date", None)
    )


def build_time_kpi(
    project,
    progress_percentage: int,
    *,
    latest_eot_date: date | None = None,
    contract_finish: date | None = None,
    project_start: date | None = None,
) -> dict[str, Any]:
    """
    Schedule elapsed % using start → latest completion (approved EOT or contract finish).
    Status reflects delay vs latest completion date.
    """
    start = (
        project_start
        or getattr(project, "project_start", None)
        or getattr(project, "start_date", None)
        or getattr(project, "commencement_date", None)
    )
    finish = resolve_completion_date(
        project,
        latest_eot_date=latest_eot_date,
        contract_finish=contract_finish,
    )
    if not start or not finish:
        return {"percentage": 0, "status": CARD_NO_DATA}

    total_days = (finish - start).days
    if total_days <= 0:
        return {"percentage": 0, "status": CARD_WATCH}

    today = date.today()
    elapsed_days = (min(today, finish) - start).days
    percentage = _clamp_pct((elapsed_days / total_days) * 100)

    delay_days = (today - finish).days  # positive = overdue
    if delay_days > CRITICAL_DELAY_DAYS:
        status = CARD_CRITICAL
    elif delay_days > 0:
        status = CARD_AT_RISK if delay_days > WATCH_DELAY_DAYS else CARD_WATCH
    elif 0 <= (finish - today).days <= AT_RISK_DAYS:
        status = CARD_AT_RISK
    elif progress_percentage + 5 < percentage:
        status = CARD_WATCH
    elif progress_percentage >= percentage:
        status = CARD_ON_TRACK
    else:
        status = CARD_WATCH

    # Map onto legacy Excellent/Watch/Delay when needed for older FE chips,
    # but prefer explicit On Track / At Risk / Critical per product request.
    return {"percentage": percentage, "status": status}


def compute_project_status(
    project,
    *,
    latest_eot_date: date | None = None,
    contract_finish: date | None = None,
) -> str:
    """
    Card-level project_status:
      Completed | Critical | At Risk | Watch | On Track | No Data
    """
    if (getattr(project, "status", None) or "").lower() == "completed":
        return STATUS_COMPLETED

    finish = resolve_completion_date(
        project,
        latest_eot_date=latest_eot_date,
        contract_finish=contract_finish,
    )
    if not finish:
        return STATUS_NO_DATA

    today = date.today()
    delay_days = (today - finish).days
    days_remaining = (finish - today).days

    if delay_days > CRITICAL_DELAY_DAYS:
        return STATUS_CRITICAL
    if delay_days > 0:
        # 1 .. CRITICAL_DELAY_DAYS overdue
        if delay_days <= WATCH_DELAY_DAYS:
            return STATUS_WATCH
        return STATUS_CRITICAL
    if 0 <= days_remaining <= AT_RISK_DAYS:
        return STATUS_AT_RISK
    return STATUS_ON_TRACK


def build_cost_kpi(cost_row) -> dict[str, Any]:
    if cost_row is None:
        return {"percentage": 0, "status": CARD_NO_DATA}
    cpi = getattr(cost_row, "cpi", None)
    domain_status = cost_status_from_cpi(cpi)
    percentage = _clamp_pct(float(cpi) * 100) if cpi is not None else 0
    if domain_status == "over_budget" and percentage >= 70:
        card_status = CARD_WATCH
    else:
        card_status = _COST_STATUS_TO_CARD.get(domain_status, CARD_WATCH)
    return {"percentage": percentage, "status": card_status}


def build_quality_kpi(quality_row) -> dict[str, Any]:
    if quality_row is None:
        return {"percentage": 0, "status": CARD_NO_DATA}
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
    Live HSE severity. If no HSE record → 0% / No Data (never stub 100%).
    """
    if hse_row is None:
        return {"percentage": 0, "status": CARD_NO_DATA}

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


def compute_health_score(
    progress: int,
    time: int,
    cost: int,
    quality: int,
    safety: int,
    *,
    weights: dict[str, float] | None = None,
) -> int:
    """
    Weighted health score 0–100.

    Default weights: Progress 25%, Time 25%, Quality 20%, Safety 20%, Cost 10%.
    """
    w = weights or HEALTH_SCORE_WEIGHTS
    parts = {
        "progress": (int(progress), float(w.get("progress", 0.25))),
        "time": (int(time), float(w.get("time", 0.25))),
        "quality": (int(quality), float(w.get("quality", 0.20))),
        "safety": (int(safety), float(w.get("safety", 0.20))),
        "cost": (int(cost), float(w.get("cost", 0.10))),
    }
    total_w = sum(weight for _, weight in parts.values()) or 1.0
    score = sum(pct * weight for pct, weight in parts.values()) / total_w
    return int(round(max(0.0, min(100.0, score))))
