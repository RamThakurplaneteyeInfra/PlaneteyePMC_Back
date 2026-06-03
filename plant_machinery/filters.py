import django_filters

from .models import MachineryItem, PlantMachineryReport


class PlantMachineryReportFilter(django_filters.FilterSet):
    report_date = django_filters.DateFilter(field_name="report_date")
    report_date_gte = django_filters.DateFilter(
        field_name="report_date", lookup_expr="gte"
    )
    report_date_lte = django_filters.DateFilter(
        field_name="report_date", lookup_expr="lte"
    )
    project_name = django_filters.CharFilter(
        field_name="project_name", lookup_expr="icontains"
    )

    class Meta:
        model = PlantMachineryReport
        fields = ["project_name", "report_date", "report_date_gte", "report_date_lte"]


class MachineryItemFilter(django_filters.FilterSet):
    machinery_master = django_filters.NumberFilter(field_name="machinery_master__id")
    particular = django_filters.CharFilter(
        field_name="machinery_master__name", lookup_expr="icontains"
    )
    status = django_filters.ChoiceFilter(choices=MachineryItem.STATUS_CHOICES)
    report = django_filters.NumberFilter(field_name="report__id")
    project_name = django_filters.CharFilter(
        field_name="report__project_name", lookup_expr="icontains"
    )

    class Meta:
        model = MachineryItem
        fields = [
            "machinery_master",
            "particular",
            "status",
            "report",
            "project_name",
        ]
