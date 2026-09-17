import django_filters

from .models import ProjectFeedback


class ProjectFeedbackFilter(django_filters.FilterSet):
    project = django_filters.NumberFilter(field_name="project_id")
    status = django_filters.CharFilter(field_name="status", lookup_expr="iexact")
    priority = django_filters.CharFilter(field_name="priority", lookup_expr="iexact")
    reported_by = django_filters.NumberFilter(field_name="reported_by_id")
    created_date = django_filters.DateFilter(field_name="created_at", lookup_expr="date")
    month = django_filters.NumberFilter(field_name="created_at", lookup_expr="month")
    year = django_filters.NumberFilter(field_name="created_at", lookup_expr="year")

    class Meta:
        model = ProjectFeedback
        fields = ["project", "status", "priority", "reported_by", "created_date", "month", "year"]
