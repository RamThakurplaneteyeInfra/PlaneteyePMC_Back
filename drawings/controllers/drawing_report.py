"""
Client drawing report row builder.

Extracts stage dates from workflow events (latest per action) with fallback
to direct date fields on DrawingRegisterItem.

KPI summary is computed directly from DrawingRegisterItem records —
DrawingSummary is no longer the source of truth for KPI calculations.
"""

from __future__ import annotations

import calendar
from datetime import date

from django.db.models import Prefetch, Q, QuerySet

from ..models.drawing_register import DrawingRegisterItem, DrawingWorkflowEvent
from .drawing_metrics import metrics_from_counts

VIEW_MONTHLY = "monthly"
VIEW_CUMULATIVE = "cumulative"
VALID_VIEWS = {VIEW_MONTHLY, VIEW_CUMULATIVE}

CLIENT_FORMAT = "client"
EXPORT_CSV = "csv"
EXPORT_EXCEL = "excel"
EXPORT_PDF = "pdf"

ACTION_TO_FIELD = {
    DrawingWorkflowEvent.ACTION_SUBMITTED: "submission_by_contractor",
    DrawingWorkflowEvent.ACTION_CONSULTANT_COMMENTED: "consultant_comments_date",
    DrawingWorkflowEvent.ACTION_RESUBMITTED: "resubmission_date",
    DrawingWorkflowEvent.ACTION_APPROVED: "approved_by_consultant",
}

DIRECT_FIELD_MAP = {
    "submission_by_contractor": "submitted_date",
    "consultant_comments_date": "consultant_comments_date",
    "resubmission_date": "resubmitted_date",
    "approved_by_consultant": "approved_date",
}

CLIENT_COLUMNS = [
    "sr_no",
    "design_and_drawing",
    "submission_by_contractor",
    "consultant_comments_date",
    "resubmission_date",
    "approved_by_consultant",
    "remarks",
]


def _iso_or_null(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _latest_dates_from_events(events: list[DrawingWorkflowEvent]) -> dict[str, date | None]:
    """Latest event_date per workflow action."""
    latest: dict[str, date | None] = {field: None for field in ACTION_TO_FIELD.values()}
    for event in events:
        field = ACTION_TO_FIELD.get(event.action)
        if not field:
            continue
        current = latest[field]
        if current is None or event.event_date > current:
            latest[field] = event.event_date
    return latest


def build_client_row(item: DrawingRegisterItem) -> dict:
    """Build one client-format report row for a register item."""
    events = list(item.workflow_events.all())
    dates = _latest_dates_from_events(events)

    for api_field, model_field in DIRECT_FIELD_MAP.items():
        if dates[api_field] is None:
            dates[api_field] = getattr(item, model_field, None)

    remarks = (item.remarks or "").strip()
    if not remarks:
        approved = dates.get("approved_by_consultant")
        if approved:
            remarks = "Approved"
        elif dates.get("submission_by_contractor"):
            remarks = "In Progress"
        else:
            remarks = "-"

    return {
        "sr_no": item.sr_no,
        "design_and_drawing": item.drawing_name,
        "submission_by_contractor": _iso_or_null(dates["submission_by_contractor"]),
        "consultant_comments_date": _iso_or_null(dates["consultant_comments_date"]),
        "resubmission_date": _iso_or_null(dates["resubmission_date"]),
        "approved_by_consultant": _iso_or_null(dates["approved_by_consultant"]),
        "remarks": remarks,
        # Extra metadata (safe for frontend; ignored by strict client parsers)
        "id": item.id,
        "revision": item.revision,
        "contractor_name": item.contractor_name or None,
        "project_name": item.project_name,
    }


def normalize_view(view: str | None) -> str:
    normalized = (view or VIEW_MONTHLY).strip().lower()
    if normalized not in VALID_VIEWS:
        return VIEW_MONTHLY
    return normalized


def period_date_range(year: int, month: int, view: str) -> tuple[date, date]:
    """Inclusive from_date and to_date for monthly or cumulative view."""
    view = normalize_view(view)
    if view == VIEW_CUMULATIVE:
        from_date = date(year, 1, 1)
    else:
        from_date = date(year, month, 1)

    last_day = calendar.monthrange(year, month)[1]
    to_date = date(year, month, last_day)
    return from_date, to_date


def _date_fields_in_period_q(from_date: date, to_date: date) -> Q:
    """Match register items with any stage date inside the period."""
    direct_fields = (
        "submitted_date",
        "consultant_comments_date",
        "resubmitted_date",
        "approved_date",
    )
    period_q = Q()
    for field in direct_fields:
        period_q |= Q(**{f"{field}__gte": from_date, f"{field}__lte": to_date})
    period_q |= Q(
        workflow_events__event_date__gte=from_date,
        workflow_events__event_date__lte=to_date,
    )
    return period_q


def _submitted_q(from_date: date, to_date: date) -> Q:
    """Items with a submission date in period (direct field or workflow event)."""
    return (
        Q(submitted_date__gte=from_date, submitted_date__lte=to_date)
        | Q(
            workflow_events__action=DrawingWorkflowEvent.ACTION_SUBMITTED,
            workflow_events__event_date__gte=from_date,
            workflow_events__event_date__lte=to_date,
        )
    )


def _approved_q(from_date: date, to_date: date) -> Q:
    """Items with an approval date in period (direct field or workflow event)."""
    return (
        Q(approved_date__gte=from_date, approved_date__lte=to_date)
        | Q(
            workflow_events__action=DrawingWorkflowEvent.ACTION_APPROVED,
            workflow_events__event_date__gte=from_date,
            workflow_events__event_date__lte=to_date,
        )
    )


def kpi_summary_for_period(
    project_name: str,
    month: int,
    year: int,
    view: str,
) -> dict:
    """
    Compute KPI summary directly from DrawingRegisterItem records.

    Counts distinct drawings that were submitted / approved within the period.
    This is the single source of truth — DrawingSummary is not consulted.
    """
    view = normalize_view(view)
    from_date, to_date = period_date_range(year, month, view)

    base_qs = DrawingRegisterItem.objects.filter(
        project__name__iexact=project_name.strip()
    )

    submitted = base_qs.filter(_submitted_q(from_date, to_date)).distinct().count()
    approved = base_qs.filter(_approved_q(from_date, to_date)).distinct().count()

    return metrics_from_counts(submitted, approved)


def build_client_report_payload(
    queryset: QuerySet,
    *,
    month: int,
    year: int,
    view: str = VIEW_MONTHLY,
    project_name: str | None = None,
) -> dict:
    """Full client report envelope with period metadata, KPIs, and rows."""
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
    }
    if project_name:
        payload["project_name"] = project_name.strip()
        payload["summary"] = kpi_summary_for_period(project_name, month, year, view)
    return payload


def build_client_report(queryset: QuerySet) -> list[dict]:
    """Build ordered client report rows from a filtered register queryset."""
    qs = queryset.select_related("project").prefetch_related(
        Prefetch(
            "workflow_events",
            queryset=DrawingWorkflowEvent.objects.order_by(
                "event_date", "created_at", "id"
            ),
        )
    )
    return [build_client_row(item) for item in qs]


def filter_register_queryset(
    queryset: QuerySet | None = None,
    *,
    project_name: str | None = None,
    month: int | None = None,
    year: int | None = None,
    view: str = VIEW_MONTHLY,
    contractor: str | None = None,
    status: str | None = None,
    search: str | None = None,
) -> QuerySet:
    """Apply standard register filters (reused by summary + register list)."""
    qs = queryset if queryset is not None else DrawingRegisterItem.objects.all()

    if project_name:
        qs = qs.filter(project__name__iexact=project_name.strip())

    if contractor:
        qs = qs.filter(contractor_name__icontains=contractor.strip())

    if status:
        qs = qs.filter(remarks__icontains=status.strip())

    if search:
        term = search.strip()
        qs = qs.filter(
            Q(drawing_name__icontains=term)
            | Q(remarks__icontains=term)
            | Q(contractor_name__icontains=term)
        )

    if year is not None and month is not None:
        from_date, to_date = period_date_range(year, month, view)
        qs = qs.filter(_date_fields_in_period_q(from_date, to_date)).distinct()
    elif year is not None:
        qs = qs.filter(
            Q(submitted_date__year=year)
            | Q(consultant_comments_date__year=year)
            | Q(resubmitted_date__year=year)
            | Q(approved_date__year=year)
            | Q(workflow_events__event_date__year=year)
        ).distinct()

    return qs.order_by("project__name", "sr_no", "revision")


def parse_report_params(
    params,
    *,
    project_name: str | None = None,
    default_year: int | None = None,
    default_month: int | None = None,
    require_period: bool = True,
) -> tuple[dict | None, str | None]:
    """
    Parse month, year, view, and filters from query params.

    Returns (parsed_dict, error_message).
    """
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

    return {
        "project_name": resolved_project,
        "month": month,
        "year": year,
        "view": normalize_view(params.get("view")),
        "contractor": params.get("contractor"),
        "status": params.get("status"),
        "search": params.get("search"),
    }, None
