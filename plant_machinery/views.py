"""
Plant & Machinery Site Asset Inventory Management
+ global Machinery Master catalogue
"""

from django.db import transaction
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from .filters import MachineryItemFilter, PlantMachineryReportFilter
from .models import MachineryItem, MachineryMaster, PlantMachineryReport
from .serializers import (
    MachineryItemSerializer,
    MachineryMasterSerializer,
    PlantMachineryReportSerializer,
)


class MachineryMasterViewSet(viewsets.ModelViewSet):
    """
    Global machinery catalogue (all projects).

    GET    /api/machinery-master/
    POST   /api/machinery-master/
    PATCH  /api/machinery-master/{id}/
    DELETE /api/machinery-master/{id}/
    """

    swagger_tags = ["Machinery Master"]

    queryset = MachineryMaster.objects.all()
    serializer_class = MachineryMasterSerializer
    filter_backends = [SearchFilter, OrderingFilter, DjangoFilterBackend]
    search_fields = ["name", "category"]
    ordering_fields = ["name", "category", "created_at"]
    ordering = ["name"]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    filterset_fields = ["category", "is_default"]

    @swagger_auto_schema(
        tags=swagger_tags,
        operation_summary="List all machinery types (available on every project)",
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(
        tags=swagger_tags,
        operation_summary="Add machinery type (instantly available on all projects)",
        request_body=MachineryMasterSerializer,
    )
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @swagger_auto_schema(tags=swagger_tags)
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @swagger_auto_schema(tags=swagger_tags)
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.log_items.exists():
            return Response(
                {
                    "detail": (
                        "Cannot delete machinery that is used in plant machinery logs. "
                        "Remove or reassign log entries first."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)


class PlantMachineryReportViewSet(viewsets.ModelViewSet):
    """Plant & Machinery daily reports with nested log items."""

    swagger_tags = ["Plant & Machinery Inventory"]

    queryset = PlantMachineryReport.objects.prefetch_related(
        "machinery_items__machinery_master"
    ).all()
    serializer_class = PlantMachineryReportSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = PlantMachineryReportFilter
    search_fields = ["project_name", "created_by"]
    ordering_fields = ["report_date", "created_at", "updated_at"]
    ordering = ["-report_date", "-created_at"]

    @swagger_auto_schema(
        tags=swagger_tags,
        operation_summary="Create or update report (upsert by project + date)",
        request_body=PlantMachineryReportSerializer,
    )
    def create(self, request, *args, **kwargs):
        """
        Create or update (upsert) by project_name + report_date.
        Re-saving the same day replaces machinery_items instead of 400.
        """
        data = (
            request.data.copy()
            if hasattr(request.data, "copy")
            else dict(request.data)
        )
        project_name = str(data.get("project_name", "")).strip()
        report_date = data.get("report_date")

        existing = None
        if project_name and report_date:
            existing = PlantMachineryReport.objects.filter(
                project_name__iexact=project_name,
                report_date=report_date,
            ).first()

        if existing is not None:
            serializer = self.get_serializer(
                existing,
                data=data,
                context={**self.get_serializer_context(), "upsert_report": existing},
            )
        else:
            serializer = self.get_serializer(data=data)

        serializer.is_valid(raise_exception=True)
        report = serializer.save()
        headers = self.get_success_headers(serializer.data)
        status_code = status.HTTP_200_OK if existing else status.HTTP_201_CREATED
        return Response(
            self.get_serializer(report).data,
            status=status_code,
            headers=headers,
        )

    @swagger_auto_schema(tags=swagger_tags)
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(tags=swagger_tags)
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(tags=swagger_tags)
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @swagger_auto_schema(tags=swagger_tags)
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @swagger_auto_schema(tags=swagger_tags)
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)

    @swagger_auto_schema(
        tags=swagger_tags,
        operation_summary="Add machinery log items to an existing report",
        request_body=MachineryItemSerializer(many=True),
    )
    @action(detail=True, methods=["post"], url_path="items")
    def add_items(self, request, pk=None):
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
                {
                    "detail": "Some items failed validation",
                    "errors": errors,
                    "created": created_items,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(created_items, status=status.HTTP_201_CREATED)


class MachineryItemViewSet(viewsets.ModelViewSet):
    """Standalone machinery log line items."""

    swagger_tags = ["Plant & Machinery Items (standalone)"]

    queryset = MachineryItem.objects.select_related(
        "report", "machinery_master"
    ).all()
    serializer_class = MachineryItemSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = MachineryItemFilter
    search_fields = ["machinery_master__name", "remark", "report__project_name"]
    ordering_fields = ["sr_no", "qty", "last_updated"]
    ordering = ["report__report_date", "sr_no"]
