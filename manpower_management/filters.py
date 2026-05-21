import django_filters
from .models import ManpowerRecord


class ManpowerRecordFilter(django_filters.FilterSet):
    """
    Filtering support for ManpowerRecord API.
    """

    project_name = django_filters.CharFilter(field_name='project_name', lookup_expr='icontains')
    month = django_filters.CharFilter(field_name='month', lookup_expr='iexact')
    year = django_filters.NumberFilter(field_name='year')
    year_gte = django_filters.NumberFilter(field_name='year', lookup_expr='gte')
    year_lte = django_filters.NumberFilter(field_name='year', lookup_expr='lte')

    class Meta:
        model = ManpowerRecord
        fields = ['project_name', 'month', 'year', 'year_gte', 'year_lte']
