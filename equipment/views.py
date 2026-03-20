"""
Project equipment API: monthly planned/actual, auto cumulative totals, dashboard series.
"""

from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
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
    permission_classes = [AllowAny]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        return ProjectEquipment.objects.all().order_by("project_name", "month")

    @swagger_auto_schema(
        tags=swagger_tags,
        operation_summary="Equipment: add monthly row (POST)",
        operation_id="equipment_create_monthly",
        request_body=ProjectEquipmentInputSerializer,
        responses={201: ProjectEquipmentSerializer},
    )
    def create(self, request, *args, **kwargs):
        ser = ProjectEquipmentInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        instance = ser.save()
        return Response(
            ProjectEquipmentSerializer(instance).data,
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
        qs = self.get_queryset()
        pn = request.query_params.get("project_name")
        if pn:
            qs = qs.filter(project_name__iexact=pn.strip())
        return Response(ProjectEquipmentSerializer(qs, many=True).data)

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
        rows = (
            ProjectEquipment.objects.filter(project_name__iexact=pn)
            .order_by("month")
        )
        months = [month_label(r.month) for r in rows]
        planned_m = [r.planned_equipment for r in rows]
        actual_m = [r.actual_equipment for r in rows]
        planned_c = [r.planned_cumulative for r in rows]
        actual_c = [r.actual_cumulative for r in rows]
        eff = [
            None if r.planned_equipment == 0
            else round(r.actual_equipment / r.planned_equipment, 4)
            for r in rows
        ]
        below = [r.actual_equipment < r.planned_equipment for r in rows]
        return Response(
            {
                "months": months,
                "planned_monthly": planned_m,
                "actual_monthly": actual_m,
                "planned_cumulative": planned_c,
                "actual_cumulative": actual_c,
                "equipment_efficiency": eff,
                "actual_below_planned": below,
            }
        )
