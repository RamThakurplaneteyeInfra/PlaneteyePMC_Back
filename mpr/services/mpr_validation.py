"""
MPR snapshot validation / normalization.

Runs after aggregation and before persist/render.
Does not invent missing business values; repairs inconsistencies and
client-facing presentation fields only.
"""

from __future__ import annotations

import re
from copy import deepcopy
from datetime import datetime
from typing import Any

from cost_performance.serializers import month_year_sort_key

# Internal merge/debug noise in project descriptions
_MERGE_TAG_RE = re.compile(
    r"\[Merged from[^\]]*\]",
    re.IGNORECASE,
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_ID_LEAK_RE = re.compile(r"\bid\s*=\s*\d+\b", re.IGNORECASE)

ENUM_LABELS: dict[str, str] = {
    "PENDING": "Pending",
    "DELIVERED_ON_TIME": "Delivered on Time",
    "DELIVERED_LATE": "Delivered Late",
    "CLIENT": "Client",
    "CONTRACTOR": "Contractor",
    "OTHER_AGENCY": "Other Agency",
    "INBOUND": "Inbound",
    "OUTBOUND_SCL": "Outbound (SCL)",
    "OUTBOUND": "Outbound",
    "OPEN": "Open",
    "IN_PROGRESS": "In Progress",
    "CLOSED": "Closed",
    "HIGH": "High",
    "MEDIUM": "Medium",
    "LOW": "Low",
    "CRITICAL": "Critical",
    "APPROVED": "Approved",
    "PENDING_APPROVAL": "Pending Approval",
    "SUBMITTED": "Submitted",
    "REJECTED": "Rejected",
    "UPDATED": "Updated",
    "NOT_UPDATED": "Not Updated",
    "YET_TO_UPDATE": "Yet to Update",
    "ISSUE": "Issue",
    "RISK": "Risk",
    "CONCERN": "Concern",
    "ACTION": "Action",
    "MOM": "Minutes of Meeting",
    "EDL": "Engineering Decision Log",
    "SCL": "SCL",
}


def _dec(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _humanize(value: Any) -> Any:
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    key = value.strip()
    if key in ENUM_LABELS:
        return ENUM_LABELS[key]
    # Title-case unknown SCREAMING_SNAKE enums
    if key.isupper() and "_" in key:
        return key.replace("_", " ").title()
    return value


def _clean_client_text(value: Any) -> Any:
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    text = _MERGE_TAG_RE.sub("", value)
    text = _HTML_TAG_RE.sub(" ", text)
    text = _ID_LEAK_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _parse_yyyy_mm(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    try:
        y, m = str(value).split("-", 1)
        return int(y), int(m)
    except Exception:
        return None


def _reconcile_activity(row: dict) -> dict:
    """Apply ScopeProgressService-compatible reconciliation."""
    out = dict(row)
    total = _dec(out.get("total"))
    completed = _dec(out.get("completed"))
    if total is None and completed is None:
        return out
    total_v = total if total is not None else 0.0
    completed_v = completed if completed is not None else 0.0
    if total_v > 0:
        raw_pct = (completed_v / total_v) * 100.0
        pct = round(min(100.0, raw_pct), 2)
        balance = round(max(total_v - completed_v, 0.0), 2)
    else:
        pct = 0.0
        balance = 0.0
    out["total"] = total
    out["completed"] = completed
    out["balance"] = balance
    out["percent_achieved"] = pct
    if total is not None and completed is not None and completed_v > total_v:
        remark = (out.get("remarks") or "").strip()
        note = "Completed quantity exceeds planned total."
        out["remarks"] = f"{remark} {note}".strip() if remark else note
        out["overachievement"] = True
    return out


def _normalize_physical(snapshot: dict, warnings: list[str]) -> None:
    physical = snapshot.get("physical_progress")
    if not isinstance(physical, dict):
        return
    period = (snapshot.get("reporting_period") or {}).get("month")
    report_ym = _parse_yyyy_mm(period)

    activities = []
    for row in physical.get("activities") or []:
        if not isinstance(row, dict):
            continue
        fixed = _reconcile_activity(row)
        total = _dec(fixed.get("total"))
        completed = _dec(fixed.get("completed"))
        pct = _dec(fixed.get("percent_achieved"))
        if pct is not None and (pct < 0 or pct > 100):
            warnings.append(
                f"Physical progress percentage out of range for '{fixed.get('item')}': {pct}"
            )
            fixed["percent_achieved"] = round(min(100.0, max(0.0, pct)), 2)
        if total and completed and completed > total:
            warnings.append(
                f"Physical progress completed exceeds total for '{fixed.get('item')}' "
                f"({completed} > {total})."
            )
        activities.append(fixed)
    # Re-number after normalization
    for i, row in enumerate(activities, start=1):
        row["sr_no"] = i
        row.pop("scope_id", None)  # never expose DB ids to client snapshot consumers
    physical["activities"] = activities

    scope_items = []
    for row in physical.get("scope_items") or []:
        if not isinstance(row, dict):
            continue
        fixed = _reconcile_activity(row)
        fixed.pop("scope_id", None)
        scope_items.append(fixed)
    for i, row in enumerate(scope_items, start=1):
        row["sr_no"] = i
    physical["scope_items"] = scope_items
    if not isinstance(physical.get("scope_category_summary"), list):
        physical["scope_category_summary"] = []

    history = []
    for row in physical.get("history") or []:
        if not isinstance(row, dict):
            continue
        ym = _parse_yyyy_mm(row.get("month"))
        if report_ym and ym and ym > report_ym:
            warnings.append(
                f"Excluded future actual progress month {row.get('month')} from chart."
            )
            continue
        history.append(row)
    history.sort(key=lambda r: _parse_yyyy_mm(r.get("month")) or (0, 0))
    physical["history"] = history

    periods = [h.get("month") for h in history if h.get("month")]
    planned = [h.get("planned_percentage") for h in history]
    actual = [h.get("actual_percentage") for h in history]
    includes_report = bool(period and period in periods)

    monthly = physical.get("monthly") or {}
    cumulative = physical.get("cumulative") or {}
    month_label = physical.get("reporting_month_label")
    if not month_label and period:
        try:
            y, m = period.split("-")
            import calendar

            month_label = f"{calendar.month_name[int(m)]} {y}"
        except (TypeError, ValueError):
            month_label = period

    unavailable_message = None
    if not includes_report and period:
        unavailable_message = (
            f"Monthly Construction Progress data is not available for {month_label}."
        )

    # Prefer compact info block when fewer than 2 historical CP periods
    # (avoids a misleading single-bar "chart"). Never invent missing months.
    min_chart_periods = 2
    render_mode = "chart" if len(periods) >= min_chart_periods else "info_block"

    historical_rows = []
    for h in history:
        ym = h.get("month")
        label = ym
        if ym:
            try:
                y, m = str(ym).split("-")
                import calendar

                label = f"{calendar.month_name[int(m)]} {y}"
            except (TypeError, ValueError):
                label = ym
        historical_rows.append(
            {
                "month": ym,
                "month_label": label,
                "planned_percentage": h.get("planned_percentage"),
                "actual_percentage": h.get("actual_percentage"),
            }
        )

    title = f"Physical Progress — {month_label}" if month_label else (
        "Physical Progress"
    )

    physical["chart"] = {
        "reporting_month": period,
        "reporting_month_label": month_label,
        "available_periods": periods,
        # Legacy alias — same series, never invents reporting-month points
        "periods": periods,
        "planned": planned,
        "actual": actual,
        "reporting_month_available": includes_report,
        "includes_reporting_month": includes_report,
        "render_mode": render_mode,
        "title": title,
        "message": unavailable_message,
        "historical_rows": historical_rows,
        "cumulative_scope_progress": cumulative.get("actual_percentage"),
        "cumulative_scope_planned_quantity": cumulative.get("scope_planned_quantity")
        or (physical.get("scope_progress") or {}).get("planned_quantity"),
        "cumulative_scope_completed_quantity": cumulative.get(
            "scope_completed_quantity"
        )
        or (physical.get("scope_progress") or {}).get("cumulative_quantity"),
        # Keep subtitle for older PDF paths; prefer message + separate cumulative KPI
        "subtitle": unavailable_message,
    }

    # Keep top-level mirrors in sync after any prior mutations
    if "available" not in monthly:
        if "monthly_available" in physical:
            monthly["available"] = bool(physical.get("monthly_available"))
        else:
            monthly["available"] = (
                monthly.get("planned_percentage") is not None
                or monthly.get("actual_percentage") is not None
            )
    physical["monthly"] = monthly
    physical["monthly_available"] = bool(monthly.get("available"))
    if monthly.get("available"):
        monthly["message"] = monthly.get("message")  # keep explicit None/clear
        if not monthly.get("message"):
            monthly["message"] = None
    elif monthly.get("message") is None and physical.get("period_note"):
        monthly["message"] = physical.get("period_note")
    physical["period_note"] = monthly.get("message")

    if isinstance(cumulative, dict):
        if "available" not in cumulative:
            cumulative["available"] = (
                cumulative.get("actual_percentage") is not None
                or cumulative.get("scope_planned_quantity") is not None
                or (physical.get("scope_progress") or {}).get("planned_quantity")
                is not None
            )
        if cumulative.get("scope_progress_percentage") is None:
            cumulative["scope_progress_percentage"] = cumulative.get(
                "actual_percentage"
            )
        physical["cumulative"] = cumulative


def _normalize_quality(snapshot: dict, warnings: list[str]) -> None:
    quality = snapshot.get("quality")
    if not isinstance(quality, dict) or not quality.get("available"):
        return
    required = _dec(quality.get("tests_required"))
    conducted = _dec(quality.get("tests_conducted"))
    passed = _dec(quality.get("tests_passed"))
    failed = _dec(quality.get("tests_failed"))

    # Client pass/fail % use conducted denominator (tests actually performed).
    if conducted and conducted > 0 and passed is not None:
        pass_pct = round((passed / conducted) * 100.0, 2)
    else:
        pass_pct = None
    if conducted and conducted > 0 and failed is not None:
        fail_pct = round((failed / conducted) * 100.0, 2)
    else:
        fail_pct = None

    if pass_pct is not None and pass_pct > 100:
        warnings.append(
            f"Quality pass% exceeded 100 before correction ({pass_pct}); "
            "recomputed from passed/conducted."
        )
        pass_pct = min(pass_pct, 100.0)
    if fail_pct is not None and fail_pct > 100:
        warnings.append(f"Quality fail% exceeded 100 ({fail_pct}).")
        fail_pct = min(fail_pct, 100.0)

    if passed is not None and failed is not None and conducted is not None:
        if passed + failed > conducted + 0.01:
            warnings.append(
                "Quality passed+failed exceeds tests conducted; "
                "percentages still use conducted denominator."
            )

    # quality_performance already means passed/conducted in shared metrics
    qp = pass_pct
    if qp is None and quality.get("quality_performance") is not None:
        qp = _dec(quality.get("quality_performance"))

    quality["pass_percentage"] = pass_pct
    quality["fail_percentage"] = fail_pct
    quality["quality_performance"] = qp
    if required is not None and conducted is not None and conducted > required:
        quality["shortfall"] = 0
        warnings.append(
            "Tests conducted exceed tests required for the reporting period."
        )


def _normalize_hse(snapshot: dict, warnings: list[str]) -> None:
    hse = snapshot.get("hse")
    if not isinstance(hse, dict) or not hse.get("available"):
        return
    rec = hse.get("record")
    if not isinstance(rec, dict):
        return

    dq = hse.get("data_quality")
    if not isinstance(dq, dict):
        dq = {"status": "valid", "warnings": []}
        hse["data_quality"] = dq

    manhours = _dec(rec.get("total_manhours"))
    man_hours_worked = _dec(rec.get("man_hours_worked"))
    working_days = rec.get("working_days")
    avg_mp = _dec(rec.get("average_daily_manpower"))
    loss = _dec(rec.get("loss_of_manhours")) or 0.0
    total_incidents = rec.get("total_incidents")
    fatalities = rec.get("fatalities")

    denom = None
    if man_hours_worked and man_hours_worked > 0:
        denom = man_hours_worked
    elif manhours and manhours > 0:
        denom = manhours

    rates_ok = True
    if dq.get("status") == "invalid":
        rates_ok = False
    if denom is None or denom <= 0:
        rates_ok = False
        warnings.append(
            "HSE rates unavailable: manhours denominator missing or zero."
        )
    elif (working_days in (0, None)) and (avg_mp in (0, None, 0.0)):
        rates_ok = False
        warnings.append(
            "HSE rates unavailable: inconsistent manpower/working-days vs manhours."
        )

    if rates_ok and denom:
        ltifr = round((loss / denom) * 1_000_000, 2)
        incidents = int(total_incidents or 0)
        incident_rate = round((incidents / denom) * 1_000_000, 2)
        if ltifr > 50_000 or incident_rate > 50_000:
            rates_ok = False
            warnings.append(
                "HSE rates suppressed: computed frequency exceeds sanity threshold."
            )
        else:
            rec["ltifr"] = ltifr
            rec["incident_rate"] = incident_rate

    if not rates_ok:
        rec["ltifr"] = None
        rec["incident_rate"] = None
        hse["rates_available"] = False
    else:
        hse["rates_available"] = True

    if fatalities is not None and int(fatalities) > 20:
        warnings.append(
            f"HSE fatalities={fatalities} for a single month looks anomalous; "
            "verify source HealthSafetyRecord data."
        )
        if dq.get("status") == "valid":
            dq["status"] = "warning"
    for w in dq.get("warnings") or []:
        if w not in warnings:
            warnings.append(w)


def _build_report_completeness(snapshot: dict, warnings: list[str]) -> dict:
    """Client/admin-friendly section completeness map (no SQL jargon)."""
    period = (snapshot.get("reporting_period") or {}).get("month") or "the reporting period"
    sections: dict[str, str] = {}
    notes: list[str] = []

    def _set(key: str, status: str, note: str | None = None):
        sections[key] = status
        if note:
            notes.append(note)

    phys = snapshot.get("physical_progress") or {}
    monthly = phys.get("monthly") or {}
    cumulative = phys.get("cumulative") or {}
    if monthly.get("available") and cumulative.get("available"):
        _set("physical_progress", "available")
    elif monthly.get("available") or cumulative.get("available"):
        note = None
        if not monthly.get("available"):
            note = monthly.get("message") or (
                f"Monthly progress data is not available for {period}."
            )
        elif not cumulative.get("available"):
            note = cumulative.get("message") or (
                f"Scope progress data for {period} is not available."
            )
        _set("physical_progress", "partial", note)
    elif phys.get("history"):
        _set(
            "physical_progress",
            "partial",
            f"Physical progress for {period} is unavailable; historical months are shown separately.",
        )
    else:
        _set(
            "physical_progress",
            "unavailable",
            f"Physical progress data for {period} is not available.",
        )

    fin = snapshot.get("financial_progress") or {}
    if fin.get("evm") or fin.get("contract"):
        _set("financial", "partial" if not fin.get("evm") else "available")
    else:
        _set("financial", "unavailable", f"Financial progress data for {period} is not available.")

    hse = snapshot.get("hse") or {}
    if not hse.get("available"):
        _set("hse", "unavailable", f"Safety data for {period} is not available.")
    else:
        dq = (hse.get("data_quality") or {}).get("status") or "valid"
        if dq == "invalid":
            _set(
                "hse",
                "warning",
                "Safety source data appears inconsistent; derived rates are not shown.",
            )
        elif dq == "warning" or not hse.get("rates_available"):
            _set(
                "hse",
                "warning",
                "Safety counts are shown; derived rates are not available.",
            )
        else:
            _set("hse", "available")

    for key, getter, label in [
        ("quality", lambda: (snapshot.get("quality") or {}).get("available"), "Quality"),
        ("drawings", lambda: bool((snapshot.get("drawings") or {}).get("total_register")), "Drawings"),
        ("eot", lambda: True, "EOT"),
        ("bg", lambda: (snapshot.get("bg") or {}).get("available"), "BG"),
        ("correspondence", lambda: bool((snapshot.get("correspondence") or {}).get("important_records") or (snapshot.get("correspondence") or {}).get("summary", {}).get("total_received")), "Correspondence"),
        ("bottlenecks", lambda: True, "Bottlenecks"),
        ("manpower", lambda: (snapshot.get("manpower") or {}).get("available"), "Manpower"),
        ("equipment", lambda: bool((snapshot.get("equipment") or {}).get("kpi") or (snapshot.get("equipment") or {}).get("plant_machinery_reports")), "Equipment"),
        ("meetings", lambda: (snapshot.get("meetings") or {}).get("available"), "Meetings"),
        ("site_photos", lambda: bool((snapshot.get("site_photos") or {}).get("photos")), "Photographs"),
        ("next_month_program", lambda: (snapshot.get("next_month_program") or {}).get("available"), "Next Month Programme"),
        ("materials", lambda: (snapshot.get("materials") or {}).get("available"), "Material Received"),
        ("laboratory_equipment", lambda: (snapshot.get("laboratory_equipment") or {}).get("available"), "Laboratory Equipment"),
    ]:
        ok = bool(getter())
        if key in ("eot", "bottlenecks"):
            sections[key] = "available"
        elif ok:
            sections[key] = "available"
        else:
            sections[key] = "unavailable"
            if key in ("materials", "laboratory_equipment", "manpower", "meetings", "next_month_program", "site_photos"):
                notes.append(f"{label} data is not available for {period}.")

    mp = snapshot.get("manpower") or {}
    if mp.get("available") and mp.get("limitations"):
        sections["manpower"] = "partial"
        notes.append("Detailed manpower classification is not available for this reporting period.")

    # Deduplicate notes
    uniq_notes = []
    for n in notes:
        if n not in uniq_notes:
            uniq_notes.append(n)
    for w in warnings:
        # Keep only client-safe warning phrasing in completeness notes
        if "anomalous" in w.lower() or "unavailable" in w.lower() or "suppressed" in w.lower():
            if w not in uniq_notes:
                uniq_notes.append(w)

    return {"sections": sections, "notes": uniq_notes}


def _normalize_financial(snapshot: dict, warnings: list[str]) -> None:
    fin = snapshot.get("financial_progress")
    if not isinstance(fin, dict):
        return
    period = (snapshot.get("reporting_period") or {}).get("month")
    report_ym = _parse_yyyy_mm(period)
    report_key = month_year_sort_key(
        datetime(report_ym[0], report_ym[1], 1).strftime("%b-%Y")
    ) if report_ym else None

    def _filter_sort(rows: list, label: str) -> list:
        out = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            my = row.get("month_year")
            key = month_year_sort_key(str(my or ""))
            if report_key and key > report_key:
                warnings.append(f"Excluded future {label} month {my}.")
                continue
            if key == (0, 0) and my:
                warnings.append(f"Unparseable {label} month_year '{my}' excluded.")
                continue
            out.append(row)
        out.sort(key=lambda r: month_year_sort_key(str(r.get("month_year") or "")))
        return out

    history = _filter_sort(fin.get("history") or [], "financial")
    cashflow_history = _filter_sort(fin.get("cashflow_history") or [], "cashflow")
    fin["history"] = history
    fin["cashflow_history"] = cashflow_history

    # Chart: last 12 actual months ending at reporting month
    chart_rows = history[-12:]
    fin["chart"] = {
        "reporting_month": period,
        "periods": [r.get("month_year") for r in chart_rows],
        "planned": [r.get("BCWS") for r in chart_rows],
        "actual": [r.get("ACWP") for r in chart_rows],
        "title": "Monthly Planned vs Actual Financial Progress",
    }


def _normalize_events_and_enums(snapshot: dict) -> None:
    corr = snapshot.get("correspondence")
    if isinstance(corr, dict):
        for rec in corr.get("important_records") or []:
            if not isinstance(rec, dict):
                continue
            rec["delivered_status"] = _humanize(rec.get("delivered_status"))
            rec["correspondence_type"] = _humanize(rec.get("correspondence_type"))
            rec["flow_direction"] = _humanize(rec.get("flow_direction"))
            rec["description"] = _clean_client_text(rec.get("description"))

    bn = snapshot.get("bottlenecks")
    if isinstance(bn, dict):
        for rec in bn.get("records") or []:
            if not isinstance(rec, dict):
                continue
            rec["priority"] = _humanize(rec.get("priority"))
            rec["status"] = _humanize(rec.get("status"))
            rec["type"] = _humanize(rec.get("type"))
            rec["description"] = _clean_client_text(rec.get("description"))

    eot = snapshot.get("eot")
    if isinstance(eot, dict):
        for rec in eot.get("history") or []:
            if isinstance(rec, dict):
                rec["status"] = _humanize(rec.get("status"))
        latest = eot.get("latest_approved_eot")
        if isinstance(latest, dict):
            latest["status"] = _humanize(latest.get("status"))
        current = eot.get("current_eot")
        if isinstance(current, dict):
            current["status"] = _humanize(current.get("status"))

    bg = snapshot.get("bg")
    if isinstance(bg, dict):
        for rec in bg.get("records") or []:
            if isinstance(rec, dict):
                rec["status"] = _humanize(rec.get("status"))
                rec["bg_type"] = _humanize(rec.get("bg_type"))

    meetings = snapshot.get("meetings")
    if isinstance(meetings, dict):
        for rec in meetings.get("records") or []:
            if isinstance(rec, dict):
                rec["meeting_type"] = _humanize(rec.get("meeting_type"))
                rec["title"] = _clean_client_text(rec.get("title"))
                rec["description"] = _clean_client_text(rec.get("description"))


def _normalize_drawings(snapshot: dict) -> None:
    drawings = snapshot.get("drawings")
    if not isinstance(drawings, dict):
        return
    for item in drawings.get("register_items") or []:
        if not isinstance(item, dict):
            continue
        # Ensure date lists are plain strings (no HTML)
        for key in ("submission_by_contractor", "reply_by_scl"):
            vals = item.get(key) or []
            cleaned = []
            for v in vals:
                if v is None:
                    continue
                text = _HTML_TAG_RE.sub("\n", str(v)).strip()
                for part in re.split(r"[\n;]+", text):
                    part = part.strip()
                    if part:
                        cleaned.append(part)
            item[key] = cleaned
        item["remarks"] = _clean_client_text(item.get("remarks")) or item.get("remarks")
        item["drawing_name"] = _clean_client_text(item.get("drawing_name")) or item.get(
            "drawing_name"
        )
        # Derive client-friendly status
        if item.get("approved_date"):
            item["status"] = "Approved"
        elif item.get("submission_by_contractor") or item.get("submitted_date"):
            item["status"] = "Under Review"
        else:
            raw_status = (item.get("remarks") or "").strip()
            item["status"] = _humanize(raw_status) if raw_status else "Pending"


def _normalize_project(snapshot: dict, warnings: list[str]) -> None:
    project = snapshot.get("project")
    if not isinstance(project, dict):
        return
    desc = project.get("description")
    cleaned = _clean_client_text(desc)
    if desc and cleaned != desc:
        warnings.append("Stripped internal merge/debug text from project description.")
    project["description"] = cleaned


def _normalize_equipment(snapshot: dict) -> None:
    eq = snapshot.get("equipment")
    if not isinstance(eq, dict):
        return
    kpi = eq.get("kpi")
    if isinstance(kpi, dict):
        eq["deployment_summary"] = {
            "label": "Equipment Deployment Summary",
            "planned": kpi.get("planned_equipment"),
            "actual": kpi.get("actual_equipment"),
            "performance_percentage": kpi.get("performance_percentage"),
            "remarks": kpi.get("remarks"),
        }


def validate_and_normalize_snapshot(snapshot: dict) -> dict:
    """
    Return a normalized deep copy of snapshot_json with validation metadata.

    ``validation`` is for backend/admin use and must not be printed in client PDF.
    """
    if not isinstance(snapshot, dict):
        return {
            "validation": {
                "status": "warning",
                "warnings": ["Snapshot missing or invalid."],
            }
        }

    out = deepcopy(snapshot)
    warnings: list[str] = []

    _normalize_project(out, warnings)
    _normalize_physical(out, warnings)
    _normalize_quality(out, warnings)
    _normalize_hse(out, warnings)
    _normalize_financial(out, warnings)
    _normalize_events_and_enums(out)
    _normalize_drawings(out)
    _normalize_equipment(out)

    # Strip technical notes that should not reach client PDF via accidental render
    da = out.get("data_availability")
    if isinstance(da, dict):
        for key, info in list(da.items()):
            if not isinstance(info, dict):
                continue
            note = info.get("note") or ""
            if any(
                token in note
                for token in (
                    "ScopeProgressService",
                    "ConstructionProgress row",
                    "closed_at",
                    "snapshot_note",
                    "Narrative text fields are not stored",
                )
            ):
                info = dict(info)
                info["note"] = "Partial or unavailable for the reporting period."
                da[key] = info

    # Soften financial contract snapshot_note
    fin = out.get("financial_progress")
    if isinstance(fin, dict):
        contract = fin.get("contract")
        if isinstance(contract, dict) and contract.get("snapshot_note"):
            contract = dict(contract)
            contract.pop("snapshot_note", None)
            fin["contract"] = contract

    eot = out.get("eot")
    if isinstance(eot, dict) and eot.get("official_completion_rule"):
        eot = dict(eot)
        eot.pop("official_completion_rule", None)
        out["eot"] = eot

    status = "valid" if not warnings else "warning"
    out["validation"] = {"status": status, "warnings": warnings}
    out["report_completeness"] = _build_report_completeness(out, warnings)
    return out
