"""
Dashboard summary metrics for bottleneck register.
"""

from django.db.models import Count, Q
from django.utils import timezone

from .models import Bottleneck


def compute_summary(queryset):
    """
    Build dashboard counts for a project (or filtered queryset).

    overdue: target_date < today AND status != CLOSED
    """
    today = timezone.localdate()
    overdue_q = Q(target_date__lt=today) & ~Q(status=Bottleneck.STATUS_CLOSED)

    type_counts = queryset.values("type").annotate(count=Count("id"))
    by_type = {row["type"]: row["count"] for row in type_counts}

    status_counts = queryset.values("status").annotate(count=Count("id"))
    by_status = {row["status"]: row["count"] for row in status_counts}

    return {
        "total_issues": by_type.get(Bottleneck.TYPE_ISSUE, 0),
        "total_concerns": by_type.get(Bottleneck.TYPE_CONCERN, 0),
        "total_risks": by_type.get(Bottleneck.TYPE_RISK, 0),
        "total_actions": by_type.get(Bottleneck.TYPE_ACTION, 0),
        "open_items": by_status.get(Bottleneck.STATUS_OPEN, 0),
        "in_progress_items": by_status.get(Bottleneck.STATUS_IN_PROGRESS, 0),
        "closed_items": by_status.get(Bottleneck.STATUS_CLOSED, 0),
        "overdue_items": queryset.filter(overdue_q).count(),
    }
