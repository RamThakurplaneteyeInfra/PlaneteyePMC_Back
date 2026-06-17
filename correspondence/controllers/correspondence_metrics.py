"""
Correspondence KPI calculations — aggregated from document records at read time.

Definitions:
  received       = total inbound documents (CLIENT / CONTRACTOR party)
  delivered      = on_time + late_deliveries (has delivered_date)
  pending        = no delivered_date
  on_time        = delivered_date <= deadline_date
  late_deliveries = delivered_date > deadline_date
  delivery_efficiency = (on_time / delivered) * 100
"""

import calendar
from datetime import date

from django.db.models import Count, Q, QuerySet

from ..models.correspondence import CorrespondenceDocument
from ..models.scl_delivered_summary import SCLDeliveredCorrespondenceSummary

STATUS_PENDING = CorrespondenceDocument.STATUS_PENDING
STATUS_DELIVERED_ON_TIME = CorrespondenceDocument.STATUS_DELIVERED_ON_TIME
STATUS_DELIVERED_LATE = CorrespondenceDocument.STATUS_DELIVERED_LATE

VIEW_MONTHLY = "monthly"
VIEW_CUMULATIVE = "cumulative"
VALID_VIEWS = {VIEW_MONTHLY, VIEW_CUMULATIVE}


def compute_delivery_efficiency(on_time: int, delivered: int) -> float:
    """Delivery efficiency = (on_time / delivered) * 100."""
    delivered = int(delivered or 0)
    if delivered == 0:
        return 0.0
    return round((int(on_time or 0) / delivered) * 100, 2)


def metrics_from_counts(
    received: int,
    on_time: int,
    late_deliveries: int,
    pending: int | None = None,
) -> dict:
    """
    Build KPI payload from counts.

    delivered is always on_time + late_deliveries (late docs count as delivered).
    """
    received = int(received or 0)
    on_time = int(on_time or 0)
    late_deliveries = int(late_deliveries or 0)
    delivered = on_time + late_deliveries

    if pending is None:
        pending = max(received - delivered, 0)
    else:
        pending = int(pending or 0)

    status_breakdown = {
        "on_time": on_time,
        "late_deliveries": late_deliveries,
        "pending": pending,
    }

    efficiency = compute_delivery_efficiency(on_time, delivered)

    return {
        "received": received,
        "delivered": delivered,
        "pending": pending,
        "on_time": on_time,
        "late_deliveries": late_deliveries,
        "status_breakdown": status_breakdown,
        "delivery_efficiency": efficiency,
        # Legacy aliases
        "correspondence_received": received,
        "correspondence_delivered": delivered,
        "pending_correspondence": pending,
    }


def metrics_from_queryset(queryset: QuerySet) -> dict:
    """Aggregate KPIs in a single database query."""
    if queryset is None:
        return metrics_from_counts(0, 0, 0, pending=0)

    agg = queryset.aggregate(
        received=Count("id"),
        on_time=Count("id", filter=Q(delivered_status=STATUS_DELIVERED_ON_TIME)),
        late_deliveries=Count("id", filter=Q(delivered_status=STATUS_DELIVERED_LATE)),
        pending=Count("id", filter=Q(delivered_status=STATUS_PENDING)),
    )
    return metrics_from_counts(
        received=agg["received"],
        on_time=agg["on_time"],
        late_deliveries=agg["late_deliveries"],
        pending=agg["pending"],
    )


def period_date_range(year: int, month: int, view: str) -> tuple[date, date]:
    """Return inclusive from_date and to_date for monthly or cumulative view."""
    if view == VIEW_CUMULATIVE:
        from_date = date(year, 1, 1)
    else:
        from_date = date(year, month, 1)

    last_day = calendar.monthrange(year, month)[1]
    to_date = date(year, month, last_day)
    return from_date, to_date


def normalize_view(view: str | None) -> str:
    normalized = (view or VIEW_MONTHLY).strip().lower()
    if normalized not in VALID_VIEWS:
        return VIEW_MONTHLY
    return normalized


def filter_by_period(
    queryset: QuerySet,
    *,
    project_name: str | None = None,
    month: int | None = None,
    year: int | None = None,
    correspondence_type: str | None = None,
    view: str = VIEW_MONTHLY,
) -> QuerySet:
    """Filter documents for dashboard period (monthly or year-to-date cumulative)."""
    view = normalize_view(view)

    if project_name:
        queryset = queryset.filter(project_name__iexact=project_name.strip())
    if year is not None:
        queryset = queryset.filter(year=year)
    if month is not None:
        if view == VIEW_CUMULATIVE:
            queryset = queryset.filter(month__lte=month)
        else:
            queryset = queryset.filter(month=month)
    if correspondence_type:
        queryset = queryset.filter(correspondence_type=correspondence_type.upper())

    return queryset


def inbound_queryset(queryset: QuerySet) -> QuerySet:
    """Inbound received/delivery tracking (CLIENT / CONTRACTOR)."""
    return queryset.filter(flow_direction=CorrespondenceDocument.FLOW_INBOUND)


def get_scl_delivered_summary(
    project_name: str,
    month: int,
    year: int,
    view: str,
) -> SCLDeliveredCorrespondenceSummary | None:
    return SCLDeliveredCorrespondenceSummary.objects.filter(
        project_name__iexact=project_name.strip(),
        month=month,
        year=year,
        view=normalize_view(view),
    ).first()


def scl_delivered_metrics(
    queryset: QuerySet,
    *,
    summary: SCLDeliveredCorrespondenceSummary | None = None,
    project_name: str | None = None,
    month: int | None = None,
    year: int | None = None,
    view: str = VIEW_MONTHLY,
) -> dict:
    """
    SCL Delivered Correspondence counts.

    Prefers stored summary; falls back to aggregating outbound SCL documents.
    """
    if summary is None and project_name and month and year:
        summary = get_scl_delivered_summary(project_name, month, year, view)

    if summary is not None:
        return summary.to_api_dict()

    delivered_q = Q(delivered_status=STATUS_DELIVERED_ON_TIME) | Q(
        delivered_status=STATUS_DELIVERED_LATE
    )
    scl_qs = queryset.filter(
        flow_direction=CorrespondenceDocument.FLOW_OUTBOUND_SCL,
        sender=CorrespondenceDocument.SENDER_SCL,
    ).filter(delivered_q)

    counts = scl_qs.values("recipient_type").annotate(count=Count("id"))
    by_recipient = {row["recipient_type"]: row["count"] for row in counts}

    client = by_recipient.get(CorrespondenceDocument.RECIPIENT_CLIENT, 0)
    contractor = by_recipient.get(CorrespondenceDocument.RECIPIENT_CONTRACTOR, 0)
    other_agency = by_recipient.get(CorrespondenceDocument.RECIPIENT_OTHER_AGENCY, 0)

    return {
        "client": client,
        "contractor": contractor,
        "other_agency": other_agency,
        "total": client + contractor + other_agency,
    }


def recent_documents_payload(queryset: QuerySet, limit: int = 10) -> list[dict]:
    """Recent documents for dashboard (newest received_date first)."""
    docs = queryset.order_by("-received_date", "-created_at")[:limit]
    return [
        {
            "id": doc.id,
            "project_name": doc.project_name,
            "month": doc.month,
            "year": doc.year,
            "correspondence_type": doc.correspondence_type,
            "flow_direction": doc.flow_direction,
            "sender": doc.sender,
            "recipient_type": doc.recipient_type,
            "sr_no": doc.sr_no,
            "description": doc.description,
            "received_date": doc.received_date.isoformat() if doc.received_date else None,
            "delivered_date": doc.delivered_date.isoformat() if doc.delivered_date else None,
            "delivered_status": doc.delivered_status,
            "deadline_date": doc.deadline_date.isoformat() if doc.deadline_date else None,
        }
        for doc in docs
    ]


def dashboard_response(
    project_name: str,
    month: int,
    year: int,
    period_qs: QuerySet,
    *,
    view: str = VIEW_MONTHLY,
) -> dict:
    """Build full dashboard payload with client, contractor, SCL, and recent docs."""
    view = normalize_view(view)
    from_date, to_date = period_date_range(year, month, view)

    inbound_qs = inbound_queryset(period_qs)
    client_qs = inbound_qs.filter(
        correspondence_type=CorrespondenceDocument.TYPE_CLIENT
    )
    contractor_qs = inbound_qs.filter(
        correspondence_type=CorrespondenceDocument.TYPE_CONTRACTOR
    )

    scl_summary = get_scl_delivered_summary(project_name, month, year, view)

    return {
        "view": view,
        "from_date": from_date.isoformat(),
        "to_date": to_date.isoformat(),
        "project_name": project_name,
        "month": month,
        "year": year,
        "client": metrics_from_queryset(client_qs),
        "contractor": metrics_from_queryset(contractor_qs),
        "scl_delivered_correspondence": scl_delivered_metrics(
            period_qs,
            summary=scl_summary,
            project_name=project_name,
            month=month,
            year=year,
            view=view,
        ),
        "recent_documents": recent_documents_payload(period_qs),
    }


def monthly_dashboard_response(
    project_name: str,
    month: int,
    year: int,
    client_qs: QuerySet,
    contractor_qs: QuerySet,
) -> dict:
    """Backward-compatible monthly-only response (no view metadata)."""
    period_qs = client_qs | contractor_qs
    return {
        "project_name": project_name,
        "month": month,
        "year": year,
        "client": metrics_from_queryset(client_qs),
        "contractor": metrics_from_queryset(contractor_qs),
    }
