"""
Correspondence KPI calculations — record counts come from documents
with correspondence_category=RECORD (never manual summary entry).
"""

import calendar
from datetime import date

from django.db.models import Count, Q, QuerySet

from ..models.correspondence import CorrespondenceDocument
from ..models.inbound_summary import InboundCorrespondenceSummary
from ..models.scl_delivered_summary import SCLDeliveredCorrespondenceSummary
from .correspondence_pending import compute_pending

STATUS_PENDING = CorrespondenceDocument.STATUS_PENDING
STATUS_DELIVERED_ON_TIME = CorrespondenceDocument.STATUS_DELIVERED_ON_TIME
STATUS_DELIVERED_LATE = CorrespondenceDocument.STATUS_DELIVERED_LATE
CATEGORY_DELIVERY = CorrespondenceDocument.CATEGORY_DELIVERY
CATEGORY_RECORD = CorrespondenceDocument.CATEGORY_RECORD

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
    record: int = 0,
    pending: int | None = None,
) -> dict:
    """
    Build KPI payload from counts.

    delivered is always on_time + late_deliveries (late docs count as delivered).
    pending defaults to max(received - delivered - record, 0).
    """
    received = int(received or 0)
    on_time = int(on_time or 0)
    late_deliveries = int(late_deliveries or 0)
    record = int(record or 0)
    delivered = on_time + late_deliveries

    if pending is None:
        pending = compute_pending(received, delivered, record)
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
        "record": record,
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


def metrics_from_summary_counts(
    received: int,
    delivered: int,
    record: int = 0,
) -> dict:
    """Build KPI payload from stored summary counts (no on_time/late split)."""
    received = int(received or 0)
    delivered = int(delivered or 0)
    record = int(record or 0)
    pending = compute_pending(received, delivered, record)

    return {
        "received": received,
        "delivered": delivered,
        "record": record,
        "pending": pending,
        "on_time": delivered,
        "late_deliveries": 0,
        "status_breakdown": {
            "on_time": delivered,
            "late_deliveries": 0,
            "pending": pending,
        },
        "delivery_efficiency": compute_delivery_efficiency(delivered, delivered),
        "correspondence_received": received,
        "correspondence_delivered": delivered,
        "pending_correspondence": pending,
    }


def record_count_from_queryset(queryset: QuerySet) -> int:
    """Count documents classified as RECORD."""
    if queryset is None:
        return 0
    return queryset.filter(correspondence_category=CATEGORY_RECORD).count()


def metrics_from_queryset(queryset: QuerySet) -> dict:
    """
    Aggregate KPIs from documents.

    received  = all documents (DELIVERY + RECORD)
    record    = documents with correspondence_category=RECORD
    delivered = DELIVERY documents with on_time + late status
    pending   = max(received - delivered - record, 0)
    """
    if queryset is None:
        return metrics_from_counts(0, 0, 0, record=0)

    received = queryset.count()
    record = record_count_from_queryset(queryset)

    delivery_qs = queryset.filter(correspondence_category=CATEGORY_DELIVERY)
    agg = delivery_qs.aggregate(
        on_time=Count("id", filter=Q(delivered_status=STATUS_DELIVERED_ON_TIME)),
        late_deliveries=Count("id", filter=Q(delivered_status=STATUS_DELIVERED_LATE)),
    )
    return metrics_from_counts(
        received=received,
        on_time=agg["on_time"],
        late_deliveries=agg["late_deliveries"],
        record=record,
    )


def _scl_category_counts(queryset: QuerySet) -> dict:
    """Per-recipient received/delivered/record/pending from documents."""
    delivered_q = Q(delivered_status=STATUS_DELIVERED_ON_TIME) | Q(
        delivered_status=STATUS_DELIVERED_LATE
    )
    received = queryset.count()
    record = record_count_from_queryset(queryset)
    delivery_qs = queryset.filter(correspondence_category=CATEGORY_DELIVERY)
    delivered = delivery_qs.filter(delivered_q).count()
    pending = compute_pending(received, delivered, record)
    return {
        "received": received,
        "delivered": delivered,
        "record": record,
        "pending": pending,
    }


def _scl_outbound_qs(queryset: QuerySet) -> QuerySet:
    return queryset.filter(
        flow_direction=CorrespondenceDocument.FLOW_OUTBOUND_SCL,
        sender=CorrespondenceDocument.SENDER_SCL,
    )


def _scl_recipient_qs(scl_qs: QuerySet, recipient: str) -> QuerySet:
    return scl_qs.filter(
        Q(recipient_type=recipient)
        | Q(correspondence_type=recipient, recipient_type__isnull=True)
    )


def merge_scl_record_from_documents(scl_payload: dict, queryset: QuerySet) -> dict:
    """Overlay document-computed record counts onto an SCL summary payload."""
    empty = {"received": 0, "delivered": 0, "record": 0, "pending": 0}
    scl_qs = _scl_outbound_qs(queryset)

    updated = dict(scl_payload)
    for key, recipient in (
        ("client", CorrespondenceDocument.RECIPIENT_CLIENT),
        ("contractor", CorrespondenceDocument.RECIPIENT_CONTRACTOR),
        ("other_agency", CorrespondenceDocument.RECIPIENT_OTHER_AGENCY),
    ):
        block = dict(updated.get(key) or empty)
        record = record_count_from_queryset(_scl_recipient_qs(scl_qs, recipient))
        block["record"] = record
        block["pending"] = compute_pending(
            block.get("received", 0),
            block.get("delivered", 0),
            record,
        )
        updated[key] = block

    totals = updated.get("totals") or dict(empty)
    totals = {
        "received": sum(updated[k]["received"] for k in ("client", "contractor", "other_agency")),
        "delivered": sum(updated[k]["delivered"] for k in ("client", "contractor", "other_agency")),
        "record": sum(updated[k]["record"] for k in ("client", "contractor", "other_agency")),
        "pending": sum(updated[k]["pending"] for k in ("client", "contractor", "other_agency")),
    }
    updated["totals"] = totals
    return updated


def inbound_block_with_document_record(
    received: int,
    delivered: int,
    document_qs: QuerySet,
) -> dict:
    """Build inbound category block; record always from documents."""
    record = record_count_from_queryset(document_qs)
    pending = compute_pending(received, delivered, record)
    return {
        "received": int(received or 0),
        "delivered": int(delivered or 0),
        "record": record,
        "pending": pending,
    }


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


def get_inbound_summary(
    project_name: str,
    month: int,
    year: int,
    view: str,
) -> InboundCorrespondenceSummary | None:
    return InboundCorrespondenceSummary.objects.filter(
        project_name__iexact=project_name.strip(),
        month=month,
        year=year,
        view=normalize_view(view),
    ).first()


def inbound_metrics(
    queryset: QuerySet,
    *,
    summary: InboundCorrespondenceSummary | None = None,
    correspondence_type: str,
    project_name: str | None = None,
    month: int | None = None,
    year: int | None = None,
    view: str = VIEW_MONTHLY,
) -> dict:
    """
    Client or Contractor KPI block.

    Record is always computed from documents (correspondence_category=RECORD).
    Received/delivered prefer stored summary when present; otherwise documents.
    """
    if summary is None and project_name and month and year:
        summary = get_inbound_summary(project_name, month, year, view)

    if summary is not None:
        if correspondence_type == CorrespondenceDocument.TYPE_CLIENT:
            block = inbound_block_with_document_record(
                summary.client_received,
                summary.client_delivered,
                queryset,
            )
        else:
            block = inbound_block_with_document_record(
                summary.contractor_received,
                summary.contractor_delivered,
                queryset,
            )
        return metrics_from_summary_counts(
            block["received"],
            block["delivered"],
            block["record"],
        )

    return metrics_from_queryset(queryset)


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

    scl_qs = _scl_outbound_qs(queryset)

    empty = {"received": 0, "delivered": 0, "record": 0, "pending": 0}

    if scl_qs.exists():
        client = _scl_category_counts(
            _scl_recipient_qs(scl_qs, CorrespondenceDocument.RECIPIENT_CLIENT),
        )
        contractor = _scl_category_counts(
            _scl_recipient_qs(scl_qs, CorrespondenceDocument.RECIPIENT_CONTRACTOR),
        )
        other_agency = _scl_category_counts(
            _scl_recipient_qs(scl_qs, CorrespondenceDocument.RECIPIENT_OTHER_AGENCY),
        )

        total_received = client["received"] + contractor["received"] + other_agency["received"]
        total_delivered = (
            client["delivered"] + contractor["delivered"] + other_agency["delivered"]
        )
        total_record = client["record"] + contractor["record"] + other_agency["record"]
        total_pending = client["pending"] + contractor["pending"] + other_agency["pending"]

        return {
            "client": client,
            "contractor": contractor,
            "other_agency": other_agency,
            "totals": {
                "received": total_received,
                "delivered": total_delivered,
                "record": total_record,
                "pending": total_pending,
            },
            "client_delivered": client["delivered"],
            "contractor_delivered": contractor["delivered"],
            "other_agency_delivered": other_agency["delivered"],
            "total": total_delivered,
        }

    if summary is not None:
        return merge_scl_record_from_documents(summary.to_api_dict(), queryset)

    return {
        "client": dict(empty),
        "contractor": dict(empty),
        "other_agency": dict(empty),
        "totals": dict(empty),
        "client_delivered": 0,
        "contractor_delivered": 0,
        "other_agency_delivered": 0,
        "total": 0,
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
            "correspondence_category": doc.correspondence_category,
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


def inbound_summary_to_api(
    summary: InboundCorrespondenceSummary,
    document_qs: QuerySet | None = None,
) -> dict:
    """Serialize inbound summary with record counts from documents."""
    client_doc_qs = CorrespondenceDocument.objects.none()
    contractor_doc_qs = CorrespondenceDocument.objects.none()
    if document_qs is not None:
        inbound_qs = inbound_queryset(document_qs)
        client_doc_qs = inbound_qs.filter(
            correspondence_type=CorrespondenceDocument.TYPE_CLIENT,
        )
        contractor_doc_qs = inbound_qs.filter(
            correspondence_type=CorrespondenceDocument.TYPE_CONTRACTOR,
        )

    return {
        "id": summary.id,
        "project_name": summary.project_name,
        "month": summary.month,
        "year": summary.year,
        "view": summary.view,
        "client": inbound_block_with_document_record(
            summary.client_received,
            summary.client_delivered,
            client_doc_qs,
        ),
        "contractor": inbound_block_with_document_record(
            summary.contractor_received,
            summary.contractor_delivered,
            contractor_doc_qs,
        ),
    }


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

    inbound_summary = get_inbound_summary(project_name, month, year, view)
    scl_summary = get_scl_delivered_summary(project_name, month, year, view)

    return {
        "view": view,
        "from_date": from_date.isoformat(),
        "to_date": to_date.isoformat(),
        "project_name": project_name,
        "month": month,
        "year": year,
        "client": inbound_metrics(
            client_qs,
            summary=inbound_summary,
            correspondence_type=CorrespondenceDocument.TYPE_CLIENT,
            project_name=project_name,
            month=month,
            year=year,
            view=view,
        ),
        "contractor": inbound_metrics(
            contractor_qs,
            summary=inbound_summary,
            correspondence_type=CorrespondenceDocument.TYPE_CONTRACTOR,
            project_name=project_name,
            month=month,
            year=year,
            view=view,
        ),
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
