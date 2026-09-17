"""
Client frequency-chart report builder and calculations.
"""

from __future__ import annotations

import calendar
import math
from datetime import date

from django.db.models import Q, QuerySet, Sum, Value
from django.db.models.functions import Coalesce

from ..models.frequency_chart import (
    FrequencyChartEntry,
    TestFrequencyMaster,
    compute_failed_tests,
    compute_shortfall,
)
from ..models.project_quality_status import ProjectQualityStatus
from .quality_metrics import metrics_from_counts

CLIENT_FORMAT = "client"
EXPORT_CSV = "csv"
VIEW_MONTHLY = "monthly"
VIEW_CUMULATIVE = "cumulative"
VALID_VIEWS = {VIEW_MONTHLY, VIEW_CUMULATIVE}

CLIENT_COLUMNS = [
    "sr_no",
    "item_description",
    "type_of_test",
    "frequency_of_test",
    "unit",
    "qty_previous_bill",
    "qty_this_bill",
    "total_qty",
    "required_tests_previous_bill",
    "required_tests_this_bill",
    "required_tests_upto_date",
    "field_lab_previous_bill",
    "field_lab_this_bill",
    "third_party_previous_bill",
    "third_party_this_bill",
    "total_tests_conducted",
    "required_tests",
    "conducted_tests",
    "passed_tests",
    "failed_tests",
    "shortfall",
    "status",
    "remarks",
]


def normalize_view(view: str | None) -> str:
    normalized = (view or VIEW_MONTHLY).strip().lower()
    if normalized not in VALID_VIEWS:
        return VIEW_MONTHLY
    return normalized


def period_date_range(year: int, month: int, view: str) -> tuple[date, date]:
    view = normalize_view(view)
    if view == VIEW_CUMULATIVE:
        from_date = date(year, 1, 1)
    else:
        from_date = date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    to_date = date(year, month, last_day)
    return from_date, to_date


def _to_float(value) -> float:
    if value is None:
        return 0.0
    return float(value)


def _resolve_frequency(entry: FrequencyChartEntry) -> tuple[float | None, float | None, str]:
    """Return (frequency_value, frequency_quantity, display) from entry or master."""
    if entry.frequency_quantity and entry.frequency_quantity > 0:
        fv = _to_float(entry.frequency_value) if entry.frequency_value else 1.0
        fq = _to_float(entry.frequency_quantity)
        display = entry.frequency_display or f"{fv:g} Test / {fq:g} {entry.unit or 'Unit'}"
        return fv, fq, display

    master = entry.frequency_master
    if master is None:
        master = resolve_frequency_master(
            entry.projectName,
            entry.item_description,
            entry.type_of_test,
        )
    if master and master.frequency_quantity and master.frequency_quantity > 0:
        fv = _to_float(master.frequency_value)
        fq = _to_float(master.frequency_quantity)
        display = master.frequency_display or f"{fv:g} Test / {fq:g} {master.unit or entry.unit or 'Unit'}"
        return fv, fq, display

    display = entry.frequency_display or (master.frequency_display if master else "")
    return None, None, display or "-"


def required_tests_for_quantity(
    qty,
    frequency_value: float | None,
    frequency_quantity: float | None,
) -> int | None:
    """Calculate required tests from quantity and frequency rule."""
    quantity = _to_float(qty)
    if quantity <= 0:
        return 0
    if not frequency_quantity or frequency_quantity <= 0:
        return None
    fv = frequency_value if frequency_value is not None else 1.0
    return math.ceil(quantity * fv / frequency_quantity)


def build_client_row(entry: FrequencyChartEntry) -> dict:
    """Transform one register entry into client report format."""
    fv, fq, frequency_display = _resolve_frequency(entry)

    qty_prev = _to_float(entry.qty_previous_bill)
    qty_this = _to_float(entry.qty_this_bill)
    total_qty = qty_prev + qty_this

    req_prev = required_tests_for_quantity(qty_prev, fv, fq)
    req_this = required_tests_for_quantity(qty_this, fv, fq)
    if req_prev is None and req_this is None:
        req_upto = None
    else:
        req_upto = (req_prev or 0) + (req_this or 0)

    field_prev = int(entry.field_lab_previous_bill or 0)
    field_this = int(entry.field_lab_this_bill or 0)
    third_prev = int(entry.third_party_previous_bill or 0)
    third_this = int(entry.third_party_this_bill or 0)
    total_conducted = field_prev + field_this + third_prev + third_this

    remarks = (entry.remarks or "").strip()
    if not remarks:
        if total_conducted == 0:
            remarks = "-"
        elif req_upto is not None and total_conducted >= req_upto:
            remarks = "Complied"
        elif req_upto is not None:
            remarks = "Pending"
        else:
            remarks = "-"

    metrics = entry.testing_metrics()

    return {
        "sr_no": entry.sr_no,
        "item_description": entry.item_description,
        "type_of_test": entry.type_of_test,
        "frequency_of_test": frequency_display,
        "unit": entry.unit or (entry.frequency_master.unit if entry.frequency_master else ""),
        "qty_previous_bill": qty_prev,
        "qty_this_bill": qty_this,
        "total_qty": total_qty,
        "required_tests_previous_bill": req_prev,
        "required_tests_this_bill": req_this,
        "required_tests_upto_date": req_upto,
        "field_lab_previous_bill": field_prev,
        "field_lab_this_bill": field_this,
        "third_party_previous_bill": third_prev,
        "third_party_this_bill": third_this,
        "total_tests_conducted": total_conducted,
        **metrics,
        "remarks": remarks,
        "id": entry.id,
        "month": entry.month,
        "year": entry.year,
        "project_name": entry.projectName,
        "activity_name": entry.activity_name or None,
        "contractor_name": entry.contractor_name or None,
    }


def build_client_report(queryset: QuerySet) -> list[dict]:
    qs = queryset.select_related("frequency_master").order_by(
        "projectName", "year", "month", "sr_no"
    )
    return [build_client_row(entry) for entry in qs]


def aggregate_testing_metrics(queryset: QuerySet) -> dict:
    """
    Aggregate manual testing metrics across chart rows.

    Returns card-friendly keys plus legacy aliases for backward compatibility.
    Failed and shortfall are computed from aggregates — never stored.
    """
    agg = queryset.aggregate(
        required=Coalesce(Sum("required_tests"), Value(0)),
        conducted=Coalesce(Sum("conducted_tests"), Value(0)),
        passed=Coalesce(Sum("passed_tests"), Value(0)),
    )
    required = int(agg["required"] or 0)
    conducted = int(agg["conducted"] or 0)
    passed = int(agg["passed"] or 0)
    failed = compute_failed_tests(conducted, passed)
    shortfall = compute_shortfall(required, conducted)

    legacy = metrics_from_counts(
        required,
        conducted,
        passed,
        failed,
        include_rates=True,
    )
    return {
        "required": required,
        "conducted": conducted,
        "passed": passed,
        "failed": failed,
        "shortfall": shortfall,
        **legacy,
    }


def kpi_summary_for_period(
    project_name: str,
    month: int,
    year: int,
    view: str,
) -> dict:
    """
    Legacy ProjectQualityStatus summary (kept for callers that need it).

    Frequency-chart dashboards prefer ``aggregate_testing_metrics`` on chart rows.
    """
    view = normalize_view(view)
    qs = ProjectQualityStatus.objects.filter(
        projectName__iexact=project_name.strip(),
        year=year,
    )
    if view == VIEW_MONTHLY:
        qs = qs.filter(month=month)
    else:
        qs = qs.filter(month__lte=month)

    agg = qs.aggregate(
        tests_required=Coalesce(Sum("tests_required"), Value(0)),
        tests_conducted=Coalesce(Sum("tests_conducted"), Value(0)),
        tests_passed=Coalesce(Sum("tests_passed"), Value(0)),
        tests_failed=Coalesce(Sum("tests_failed"), Value(0)),
    )
    metrics = metrics_from_counts(
        agg["tests_required"],
        agg["tests_conducted"],
        agg["tests_passed"],
        agg["tests_failed"],
        include_rates=True,
    )
    return {
        "required": metrics["tests_required"],
        "conducted": metrics["tests_conducted"],
        "passed": metrics["tests_passed"],
        "failed": metrics["tests_failed"],
        "shortfall": metrics["shortfall"],
        **metrics,
    }


def build_client_report_payload(
    queryset: QuerySet,
    *,
    month: int,
    year: int,
    view: str = VIEW_MONTHLY,
    project_name: str | None = None,
) -> dict:
    view = normalize_view(view)
    from_date, to_date = period_date_range(year, month, view)
    rows = build_client_report(queryset)

    payload = {
        "view": view,
        "from_date": from_date.isoformat(),
        "to_date": to_date.isoformat(),
        "month": month,
        "year": year,
        "rows": rows,
        "summary": aggregate_testing_metrics(queryset),
    }
    if project_name:
        payload["project_name"] = project_name.strip()
    return payload


def filter_frequency_chart_queryset(
    queryset: QuerySet | None = None,
    *,
    project_name: str | None = None,
    month: int | None = None,
    year: int | None = None,
    view: str = VIEW_MONTHLY,
    activity: str | None = None,
    test_type: str | None = None,
    contractor: str | None = None,
    search: str | None = None,
    include_archived: bool = False,
) -> QuerySet:
    qs = queryset if queryset is not None else FrequencyChartEntry.objects.all()

    if not include_archived:
        qs = qs.filter(is_archived=False)

    if project_name:
        qs = qs.filter(projectName__iexact=project_name.strip())

    if year is not None:
        if month is not None:
            view = normalize_view(view)
            if view == VIEW_CUMULATIVE:
                qs = qs.filter(year=year, month__lte=month)
            else:
                qs = qs.filter(year=year, month=month)
        else:
            qs = qs.filter(year=year)

    if activity:
        qs = qs.filter(activity_name__icontains=activity.strip())

    if test_type:
        qs = qs.filter(type_of_test__icontains=test_type.strip())

    if contractor:
        qs = qs.filter(contractor_name__icontains=contractor.strip())

    if search:
        term = search.strip()
        qs = qs.filter(
            Q(item_description__icontains=term)
            | Q(type_of_test__icontains=term)
            | Q(remarks__icontains=term)
            | Q(activity_name__icontains=term)
        )

    return qs


def parse_report_params(
    params,
    *,
    project_name: str | None = None,
    default_year: int | None = None,
    default_month: int | None = None,
    require_period: bool = True,
) -> tuple[dict | None, str | None]:
    resolved_project = (
        (project_name or params.get("project_name") or params.get("projectName") or "")
        .strip()
        or None
    )

    month_raw = params.get("month", default_month)
    year_raw = params.get("year", default_year)

    if require_period and (month_raw in (None, "") or year_raw in (None, "")):
        return None, "month and year are required."

    try:
        month = int(month_raw)
        year = int(year_raw)
    except (TypeError, ValueError):
        return None, "month and year must be valid integers."

    if not (1 <= month <= 12):
        return None, "month must be between 1 and 12."
    if not (2000 <= year <= 2100):
        return None, "year must be between 2000 and 2100."

    include_archived = str(params.get("include_archived", "")).lower() in (
        "1",
        "true",
        "yes",
    )

    return {
        "project_name": resolved_project,
        "month": month,
        "year": year,
        "view": normalize_view(params.get("view")),
        "activity": params.get("activity") or params.get("activity_name"),
        "test_type": params.get("test_type") or params.get("type_of_test"),
        "contractor": params.get("contractor") or params.get("contractor_name"),
        "search": params.get("search"),
        "include_archived": include_archived,
    }, None


def resolve_frequency_master(
    project_name: str,
    item_description: str,
    type_of_test: str,
) -> TestFrequencyMaster | None:
    """Pick project-specific master, then global template."""
    base = TestFrequencyMaster.objects.filter(
        is_archived=False,
        item_description__iexact=item_description.strip(),
        type_of_test__iexact=type_of_test.strip(),
    )
    project_rule = base.filter(projectName__iexact=project_name.strip()).first()
    if project_rule:
        return project_rule
    return base.filter(projectName="").first()
