"""
Correspondence KPI calculations — aggregated from document records at read time.

Definitions:
  received       = total documents
  delivered      = on_time + late_deliveries (has delivered_date)
  pending        = no delivered_date
  on_time        = delivered_date <= deadline_date
  late_deliveries = delivered_date > deadline_date
  delivery_efficiency = (on_time / delivered) * 100
"""

from django.db.models import QuerySet

from ..models.correspondence import CorrespondenceDocument

STATUS_PENDING = CorrespondenceDocument.STATUS_PENDING
STATUS_DELIVERED_ON_TIME = CorrespondenceDocument.STATUS_DELIVERED_ON_TIME
STATUS_DELIVERED_LATE = CorrespondenceDocument.STATUS_DELIVERED_LATE


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
    if queryset is None:
        return metrics_from_counts(0, 0, 0, pending=0)

    received = queryset.count()
    on_time = queryset.filter(
        delivered_status=STATUS_DELIVERED_ON_TIME
    ).count()
    late_deliveries = queryset.filter(
        delivered_status=STATUS_DELIVERED_LATE
    ).count()
    pending = queryset.filter(delivered_status=STATUS_PENDING).count()

    return metrics_from_counts(
        received=received,
        on_time=on_time,
        late_deliveries=late_deliveries,
        pending=pending,
    )


def filter_by_period(
    queryset: QuerySet,
    *,
    project_name: str | None = None,
    month: int | None = None,
    year: int | None = None,
    correspondence_type: str | None = None,
) -> QuerySet:
    if project_name:
        queryset = queryset.filter(project_name__iexact=project_name.strip())
    if year is not None:
        queryset = queryset.filter(year=year)
    if month is not None:
        queryset = queryset.filter(month=month)
    if correspondence_type:
        queryset = queryset.filter(correspondence_type=correspondence_type.upper())
    return queryset


def monthly_dashboard_response(
    project_name: str,
    month: int,
    year: int,
    client_qs: QuerySet,
    contractor_qs: QuerySet,
) -> dict:
    return {
        "project_name": project_name,
        "month": month,
        "year": year,
        "client": metrics_from_queryset(client_qs),
        "contractor": metrics_from_queryset(contractor_qs),
    }
