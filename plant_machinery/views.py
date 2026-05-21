"""
Plant & Machinery Site Asset Inventory Management
DRF ViewSets with full CRUD, nested items, filters, search, ordering, pagination and Swagger docs.
"""

from django.db import transaction
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend

from .models import PlantMachineryReport, MachineryItem
from .serializers import (
    PlantMachineryReportSerializer,
    MachineryItemSerializer,
)
from .filters import PlantMachineryReportFilter, MachineryItemFilter


class PlantMachineryReportViewSet(viewsets.ModelViewSet):
    """
    ViewSet for PlantMachineryReport.

    Endpoints:
    - POST   /api/plant-machinery/                 Create report + optional nested items
    - GET    /api/plant-machinery/                 List (paginated, searchable, filterable)
    - GET    /api/plant-machinery/<id>/            Retrieve single report with items
    - PUT    /api/plant-machinery/<id>/            Full update (can include machinery_items)
    - PATCH  /api/plant-machinery/<id>/            Partial update
    - DELETE /api/plant-machinery/<id>/            Delete report (cascades items)

    Extra action:
    - POST   /api/plant-machinery/<id>/items/      Add one or more items to existing report
    """

    swagger_tags = ["Plant & Machinery Inventory"]

    queryset = PlantMachineryReport.objects.prefetch_related('machinery_items').all()
    serializer_class = PlantMachineryReportSerializer
    permission_classes = [AllowAny]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = PlantMachineryReportFilter
    search_fields = ['project_name', 'created_by']
    ordering_fields = ['report_date', 'created_at', 'updated_at']
    ordering = ['-report_date', '-created_at']  # Latest reports first

    @swagger_auto_schema(
        tags=swagger_tags,
        operation_summary="Create a new Plant & Machinery report (with optional items)",
        request_body=PlantMachineryReportSerializer,
        responses={201: PlantMachineryReportSerializer},
    )
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    @swagger_auto_schema(
        tags=swagger_tags,
        operation_summary="List all Plant & Machinery reports (paginated)",
        manual_parameters=[
            openapi.Parameter('project_name', openapi.IN_QUERY, description="Filter by project name (icontains)", type=openapi.TYPE_STRING),
            openapi.Parameter('report_date', openapi.IN_QUERY, description="Exact date filter (YYYY-MM-DD)", type=openapi.TYPE_STRING, format=openapi.FORMAT_DATE),
            openapi.Parameter('report_date_gte', openapi.IN_QUERY, description="Date >= (YYYY-MM-DD)", type=openapi.TYPE_STRING, format=openapi.FORMAT_DATE),
            openapi.Parameter('report_date_lte', openapi.IN_QUERY, description="Date <= (YYYY-MM-DD)", type=openapi.TYPE_STRING, format=openapi.FORMAT_DATE),
            openapi.Parameter('search', openapi.IN_QUERY, description="Search in project_name or created_by", type=openapi.TYPE_STRING),
            openapi.Parameter('ordering', openapi.IN_QUERY, description="Order by: report_date, -report_date, created_at, etc.", type=openapi.TYPE_STRING),
        ],
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(
        tags=swagger_tags,
        operation_summary="Retrieve a single report with all its machinery items",
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(
        tags=swagger_tags,
        operation_summary="Update a report (PUT replaces machinery_items if provided)",
        request_body=PlantMachineryReportSerializer,
    )
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @swagger_auto_schema(
        tags=swagger_tags,
        operation_summary="Partial update a report",
    )
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @swagger_auto_schema(
        tags=swagger_tags,
        operation_summary="Delete a report and all its items",
    )
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)

    @swagger_auto_schema(
        tags=swagger_tags,
        operation_summary="Add one or more machinery items to an existing report",
        request_body=MachineryItemSerializer(many=True),
        responses={201: MachineryItemSerializer(many=True)},
    )
    @action(detail=True, methods=['post'], url_path='items')
    def add_items(self, request, pk=None):
        """POST /api/plant-machinery/{id}/items/"""
        report = self.get_object()
        items_data = request.data if isinstance(request.data, list) else [request.data]

        created_items = []
        errors = []

        with transaction.atomic():
            for idx, item_data in enumerate(items_data):
                ser = MachineryItemSerializer(data=item_data)
                if ser.is_valid():
                    item = ser.save(report=report)
                    created_items.append(MachineryItemSerializer(item).data)
                else:
                    errors.append({f"item_{idx}": ser.errors})

        if errors:
            return Response(
                {"detail": "Some items failed validation", "errors": errors, "created": created_items},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(created_items, status=status.HTTP_201_CREATED)


class MachineryItemViewSet(viewsets.ModelViewSet):
    """
    Standalone ViewSet for MachineryItem.

    Useful for direct item operations from frontend:
    - PUT    /api/items/<item_id>/     Update single item
    - DELETE /api/items/<item_id>/     Delete single item
    - GET    /api/items/               List all items across reports (filtered)
    """

    swagger_tags = ["Plant & Machinery Items (standalone)"]

    queryset = MachineryItem.objects.select_related('report').all()
    serializer_class = MachineryItemSerializer
    permission_classes = [AllowAny]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = MachineryItemFilter
    search_fields = ['particular', 'remark', 'report__project_name']
    ordering_fields = ['sr_no', 'qty', 'last_updated']
    ordering = ['report__report_date', 'sr_no']

    @swagger_auto_schema(
        tags=swagger_tags,
        operation_summary="Update a single machinery item (PUT / PATCH)",
    )
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @swagger_auto_schema(
        tags=swagger_tags,
        operation_summary="Delete a single machinery item",
    )
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)
