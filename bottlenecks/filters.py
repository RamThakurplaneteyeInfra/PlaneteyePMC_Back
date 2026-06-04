import django_filters

from .models import Bottleneck


class BottleneckFilter(django_filters.FilterSet):
    project_id = django_filters.NumberFilter(field_name="project_id")
    type = django_filters.ChoiceFilter(choices=Bottleneck.TYPE_CHOICES)
    status = django_filters.ChoiceFilter(choices=Bottleneck.STATUS_CHOICES)
    priority = django_filters.ChoiceFilter(choices=Bottleneck.PRIORITY_CHOICES)
    assigned_to = django_filters.NumberFilter(field_name="assigned_to_id")
    target_date = django_filters.DateFilter(field_name="target_date")
    target_date_before = django_filters.DateFilter(
        field_name="target_date", lookup_expr="lte"
    )
    target_date_after = django_filters.DateFilter(
        field_name="target_date", lookup_expr="gte"
    )

    class Meta:
        model = Bottleneck
        fields = [
            "project_id",
            "type",
            "status",
            "priority",
            "assigned_to",
            "target_date",
        ]
