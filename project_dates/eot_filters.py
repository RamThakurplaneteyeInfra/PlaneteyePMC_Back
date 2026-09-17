"""Filters for ProjectEOT list API (legacy + additive filters)."""

from __future__ import annotations

import django_filters

from project_dates.eot_models import ProjectEOT


class ProjectEOTFilter(django_filters.FilterSet):
    project = django_filters.NumberFilter(field_name="project_id")
    project_name = django_filters.CharFilter(
        field_name="project__name", lookup_expr="icontains"
    )
    status = django_filters.CharFilter(field_name="status", lookup_expr="iexact")
    is_active = django_filters.BooleanFilter(field_name="is_active")
    date_type = django_filters.CharFilter(
        field_name="project_dates__date_type", lookup_expr="iexact"
    )
    contractor = django_filters.NumberFilter(field_name="project_dates__contractor_id")
    contractor_id = django_filters.NumberFilter(field_name="project_dates__contractor_id")
    contractor_name = django_filters.CharFilter(
        field_name="project_dates__contractor_name", lookup_expr="icontains"
    )
    # Legacy date filters against stored revised completion (exposed as eot_date)
    eot_date = django_filters.DateFilter(field_name="revised_completion_date")
    contract_finish = django_filters.DateFilter(field_name="original_completion_date")
    month = django_filters.NumberFilter(method="filter_month")
    year = django_filters.NumberFilter(method="filter_year")

    class Meta:
        model = ProjectEOT
        fields = [
            "project",
            "project_name",
            "status",
            "is_active",
            "eot_number",
            "date_type",
            "contractor",
            "contractor_id",
            "contractor_name",
        ]

    def filter_month(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(created_at__month=value)

    def filter_year(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(created_at__year=value)
