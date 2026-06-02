"""
Django-filter FilterSet for ProjectDates.

Supports filtering by:
  ?project_name=Thane Project   (case-insensitive partial match)
  ?date_type=SCL
  ?date_type=CONTRACTOR
"""

import django_filters

from .models import ProjectDates


class ProjectDatesFilter(django_filters.FilterSet):
    project_name = django_filters.CharFilter(
        field_name="project__name",
        lookup_expr="icontains",
        label="Project name (partial, case-insensitive)",
    )
    date_type = django_filters.ChoiceFilter(
        choices=ProjectDates.DATE_TYPE_CHOICES,
        label="Date type (SCL or CONTRACTOR)",
    )

    class Meta:
        model = ProjectDates
        fields = ["project_name", "date_type"]
