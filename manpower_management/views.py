"""
Manpower Management System - DRF ViewSet
"""

from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from rest_framework import viewsets
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend

from .models import ManpowerRecord
from .serializers import ManpowerRecordSerializer
from .filters import ManpowerRecordFilter


class ManpowerRecordViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Manpower Management.

    Endpoints:
    - POST   /api/manpower/          → Create record
    - GET    /api/manpower/          → List records (paginated + filtered)
    - GET    /api/manpower/{id}/     → Retrieve single record
    - PUT    /api/manpower/{id}/     → Update record
    - PATCH  /api/manpower/{id}/     → Partial update
    - DELETE /api/manpower/{id}/     → Delete record
    """

    swagger_tags = ["Manpower Management"]

    queryset = ManpowerRecord.objects.all()
    serializer_class = ManpowerRecordSerializer

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = ManpowerRecordFilter
    search_fields = ['project_name', 'remarks', 'month']
    ordering_fields = ['created_at', 'updated_at', 'year', 'monthly_planned_manpower', 'actual_manpower', 'difference']
    ordering = ['-created_at']  # Latest first by default

    @swagger_auto_schema(
        tags=swagger_tags,
        operation_summary="Create a new manpower record",
        request_body=ManpowerRecordSerializer,
    )
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @swagger_auto_schema(
        tags=swagger_tags,
        operation_summary="List all manpower records (supports pagination, search, filtering)",
        manual_parameters=[
            openapi.Parameter('project_name', openapi.IN_QUERY, description="Filter by project name (partial match)", type=openapi.TYPE_STRING),
            openapi.Parameter('month', openapi.IN_QUERY, description="Filter by month (e.g. May, January)", type=openapi.TYPE_STRING),
            openapi.Parameter('year', openapi.IN_QUERY, description="Filter by year (e.g. 2026)", type=openapi.TYPE_INTEGER),
            openapi.Parameter('year_gte', openapi.IN_QUERY, description="Year greater than or equal", type=openapi.TYPE_INTEGER),
            openapi.Parameter('year_lte', openapi.IN_QUERY, description="Year less than or equal", type=openapi.TYPE_INTEGER),
            openapi.Parameter('search', openapi.IN_QUERY, description="Search in project_name, month, remarks", type=openapi.TYPE_STRING),
            openapi.Parameter('ordering', openapi.IN_QUERY, description="Order by: -created_at, year, difference, etc.", type=openapi.TYPE_STRING),
            openapi.Parameter('page', openapi.IN_QUERY, description="Page number for pagination", type=openapi.TYPE_INTEGER),
        ],
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(tags=swagger_tags, operation_summary="Retrieve a single manpower record")
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(tags=swagger_tags, operation_summary="Update a manpower record (PUT)")
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @swagger_auto_schema(tags=swagger_tags, operation_summary="Partial update a manpower record")
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @swagger_auto_schema(tags=swagger_tags, operation_summary="Delete a manpower record")
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)
