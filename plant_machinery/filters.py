import django_filters
from .models import PlantMachineryReport, MachineryItem


class PlantMachineryReportFilter(django_filters.FilterSet):
    """
    Filters for PlantMachineryReport list endpoint.
    Supports:
    - project_name (icontains search via separate SearchFilter too)
    - report_date (exact, gte, lte)
    """
    report_date = django_filters.DateFilter(field_name='report_date')
    report_date_gte = django_filters.DateFilter(field_name='report_date', lookup_expr='gte')
    report_date_lte = django_filters.DateFilter(field_name='report_date', lookup_expr='lte')
    project_name = django_filters.CharFilter(field_name='project_name', lookup_expr='icontains')

    class Meta:
        model = PlantMachineryReport
        fields = ['project_name', 'report_date', 'report_date_gte', 'report_date_lte']


class MachineryItemFilter(django_filters.FilterSet):
    """
    Filters for individual MachineryItem (standalone endpoint).
    """
    particular = django_filters.CharFilter(field_name='particular', lookup_expr='icontains')
    status = django_filters.ChoiceFilter(choices=MachineryItem.STATUS_CHOICES)
    report = django_filters.NumberFilter(field_name='report__id')
    project_name = django_filters.CharFilter(field_name='report__project_name', lookup_expr='icontains')

    class Meta:
        model = MachineryItem
        fields = ['particular', 'status', 'report', 'project_name']
