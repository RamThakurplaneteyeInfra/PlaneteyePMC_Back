"""
Project equipment API: monthly planned/actual, auto cumulative totals, dashboard series.
"""

from django.core.cache import cache
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from .models import ProjectEquipment
from .serializers import (
    month_label,
    ProjectEquipmentInputSerializer,
    ProjectEquipmentSerializer,
)


class ProjectEquipmentViewSet(viewsets.ModelViewSet):
    """
    POST /api/equipment/           — add monthly row (cumulatives recalculated)
    GET  /api/equipment/           — all rows, project_name then month ascending
    GET  /api/equipment/dashboard/ — chart-ready arrays (?project_name= required)
    """

    # Group all operations under one Swagger tag (easy to find)
    swagger_tags = ["Equipment — project tracking"]

    queryset = ProjectEquipment.objects.all()
    serializer_class = ProjectEquipmentSerializer
    http_method_names = ["get", "post", "head", "options"]
    pagination_class = PageNumberPagination

    def get_queryset(self):
        return ProjectEquipment.objects.only(
            "id", "project_name", "month", "planned_equipment", "actual_equipment",
            "planned_cumulative", "actual_cumulative", "created_at"
        ).order_by("project_name", "month")

    @swagger_auto_schema(
        tags=swagger_tags,
        operation_summary="Equipment: add monthly row (POST)",
        operation_id="equipment_create_monthly",
        request_body=ProjectEquipmentInputSerializer,
        responses={201: ProjectEquipmentSerializer},
    )
    def perform_create(self, serializer):
        super().perform_create(serializer)
        # Cache invalidation (safe for both LocMemCache and Redis backends)
        try:
            cache.delete_pattern("equipment_list:*")
            cache.delete_pattern("equipment_dashboard:*")
        except AttributeError:
            # LocMemCache doesn't support delete_pattern; clear all cache
            cache.clear()

    def create(self, request, *args, **kwargs):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        self.perform_create(ser)
        return Response(
            ProjectEquipmentSerializer(ser.instance).data,
            status=status.HTTP_201_CREATED,
        )

    @swagger_auto_schema(
        tags=swagger_tags,
        operation_summary="Equipment: list all rows (GET)",
        operation_id="equipment_list",
        manual_parameters=[
            openapi.Parameter(
                "project_name",
                openapi.IN_QUERY,
                description="Filter by project (optional)",
                type=openapi.TYPE_STRING,
            ),
        ],
    )
    def list(self, request, *args, **kwargs):
        cache_key = f"equipment_list:{request.get_full_path()}"
        data = cache.get(cache_key)
        if data is not None:
            return Response(data)

        response = super().list(request, *args, **kwargs)
        cache.set(cache_key, response.data, 300)  # 5 minutes
        return response

    @swagger_auto_schema(auto_schema=None)
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(
        tags=swagger_tags,
        operation_summary="Equipment: dashboard chart data (GET)",
        operation_id="equipment_dashboard",
        manual_parameters=[
            openapi.Parameter(
                "project_name",
                openapi.IN_QUERY,
                description="Project name (required)",
                type=openapi.TYPE_STRING,
                required=True,
            ),
        ],
        responses={
            200: openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "months": openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(type=openapi.TYPE_STRING),
                    ),
                    "planned_monthly": openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(type=openapi.TYPE_INTEGER),
                    ),
                    "actual_monthly": openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(type=openapi.TYPE_INTEGER),
                    ),
                    "planned_cumulative": openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(type=openapi.TYPE_INTEGER),
                    ),
                    "actual_cumulative": openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(type=openapi.TYPE_INTEGER),
                    ),
                    "equipment_efficiency": openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(type=openapi.TYPE_NUMBER),
                    ),
                    "actual_below_planned": openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(type=openapi.TYPE_BOOLEAN),
                    ),
                },
            ),
            400: "Missing project_name",
        },
    )
    @action(detail=False, methods=["get"], url_path="dashboard")
    def dashboard(self, request):
        pn = (request.query_params.get("project_name") or "").strip()
        if not pn:
            return Response(
                {"detail": "Query parameter project_name is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cache_key = f"equipment_dashboard:{pn}"
        data = cache.get(cache_key)
        if data is not None:
            return Response(data)

        rows = (
            ProjectEquipment.objects.filter(project_name__iexact=pn)
            .only("month", "planned_equipment", "actual_equipment", "planned_cumulative", "actual_cumulative")
            .order_by("month")
        )

        # Pre-allocate lists
        months = []
        planned_monthly = []
        actual_monthly = []
        planned_cumulative = []
        actual_cumulative = []
        equipment_efficiency = []
        actual_below_planned = []

        for r in rows:
            months.append(month_label(r.month))
            planned_monthly.append(r.planned_equipment)
            actual_monthly.append(r.actual_equipment)
            planned_cumulative.append(r.planned_cumulative)
            actual_cumulative.append(r.actual_cumulative)
            if r.planned_equipment == 0:
                equipment_efficiency.append(None)
            else:
                equipment_efficiency.append(round(r.actual_equipment / r.planned_equipment, 4))
            actual_below_planned.append(r.actual_equipment < r.planned_equipment)

        data = {
            "months": months,
            "planned_monthly": planned_monthly,
            "actual_monthly": actual_monthly,
            "planned_cumulative": planned_cumulative,
            "actual_cumulative": actual_cumulative,
            "equipment_efficiency": equipment_efficiency,
            "actual_below_planned": actual_below_planned,
        }

        cache.set(cache_key, data, 300)  # 5 minutes
        return Response(data)
