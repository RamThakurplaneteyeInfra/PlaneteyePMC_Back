"""Query filters for Reminder list scopes."""

from __future__ import annotations

from datetime import timedelta

import django_filters
from django.db.models import Q
from django.utils import timezone

from .models import Reminder


class ReminderFilter(django_filters.FilterSet):
    project_id = django_filters.NumberFilter(field_name="project_id")
    status = django_filters.CharFilter(field_name="status")
    assigned_to = django_filters.NumberFilter(field_name="assigned_to_id")
    created_by = django_filters.NumberFilter(field_name="created_by_id")
    scope = django_filters.CharFilter(method="filter_scope")
    search = django_filters.CharFilter(method="filter_search")

    class Meta:
        model = Reminder
        fields = ["project_id", "status", "assigned_to", "created_by"]

    def filter_search(self, queryset, name, value):
        text = (value or "").strip()
        if not text:
            return queryset
        return queryset.filter(
            Q(title__icontains=text)
            | Q(description__icontains=text)
            | Q(project__name__icontains=text)
        )

    def filter_scope(self, queryset, name, value):
        scope = (value or "").strip().lower()
        if not scope or scope in {"all", "*"}:
            return queryset

        now = timezone.now()
        start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_today = start_today + timedelta(days=1)
        pending = queryset.filter(status=Reminder.STATUS_PENDING)

        if scope == "overdue":
            return pending.filter(
                Q(snoozed_until__isnull=False, snoozed_until__lt=now)
                | Q(snoozed_until__isnull=True, due_at__lt=now)
            )

        if scope in {"today", "due_today"}:
            return pending.filter(
                Q(
                    snoozed_until__isnull=False,
                    snoozed_until__gte=start_today,
                    snoozed_until__lt=end_today,
                )
                | Q(
                    snoozed_until__isnull=True,
                    due_at__gte=start_today,
                    due_at__lt=end_today,
                )
            )

        if scope == "upcoming":
            return pending.filter(
                Q(snoozed_until__isnull=False, snoozed_until__gte=now)
                | Q(snoozed_until__isnull=True, due_at__gte=now)
            )

        if scope == "mine":
            user = getattr(self.request, "user", None)
            if user is None or not getattr(user, "is_authenticated", False):
                return queryset.none()
            return queryset.filter(Q(assigned_to=user) | Q(created_by=user))

        return queryset
