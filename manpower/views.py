"""
Manpower & man-hours API: monthly planned/actual, MH, cumulative MH, dashboard series.
"""

from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import ProjectManpower
from .serializers import (
    dashboard_month_label,
    month_year_sort_key,
    ProjectManpowerInputSerializer,
    ProjectManpowerSerializer,
)

swagger_tags = ["Manpower — MH tracking"]

_MANPOWER_POST_EXAMPLE = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    required=[
        "project_name",
        "month_year",
        "planned_manpower",
        "actual_manpower",
        "working_hours_per_day",
        "working_days_per_month",
    ],
    properties={
        "project_name": openapi.Schema(
            type=openapi.TYPE_STRING,
            description="Project name",
            example="Site Alpha",
        ),
        "month_year": openapi.Schema(
            type=openapi.TYPE_STRING,
            description='Month-year, format "Jan-2023"',
            example="Jan-2023",
        ),
        "planned_manpower": openapi.Schema(
            type=openapi.TYPE_INTEGER,
            description="Planned headcount for the month",
            example=50,
        ),
        "actual_manpower": openapi.Schema(
            type=openapi.TYPE_INTEGER,
            description="Actual headcount for the month",
            example=25,
        ),
        "working_hours_per_day": openapi.Schema(
            type=openapi.TYPE_NUMBER,
            description="Hours per person per day (> 0)",
            example=8.0,
        ),
        "working_days_per_month": openapi.Schema(
            type=openapi.TYPE_INTEGER,
            description="Working days in the month (> 0)",
            example=26,
        ),
    },
)


class ProjectManpowerViewSet(viewsets.ModelViewSet):
    queryset = ProjectManpower.objects.all()
    serializer_class = ProjectManpowerSerializer
    permission_classes = [AllowAny]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        qs = ProjectManpower.objects.all()
        pn = self.request.query_params.get("project_name")
        if pn:
            qs = qs.filter(project_name__iexact=pn.strip())
        return qs

    @swagger_auto_schema(
        tags=swagger_tags,
        operation_summary="Manpower: add monthly row (POST)",
        operation_id="manpower_create",
        request_body=_MANPOWER_POST_EXAMPLE,
        responses={
            201: openapi.Response(
                "Row with computed MH and cumulatives",
                ProjectManpowerSerializer,
            ),
        },
    )
    def create(self, request, *args, **kwargs):
        ser = ProjectManpowerInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        instance = ser.save()
        return Response(
            ProjectManpowerSerializer(instance).data,
            status=status.HTTP_201_CREATED,
        )

    @swagger_auto_schema(
        tags=swagger_tags,
        operation_summary="Manpower: list rows (GET)",
        operation_id="manpower_list",
        manual_parameters=[
            openapi.Parameter(
                "project_name",
                openapi.IN_QUERY,
                description="Filter by project (optional)",
                type=openapi.TYPE_STRING,
            ),
        ],
        responses={200: ProjectManpowerSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        qs = ProjectManpower.objects.all()
        pn = request.query_params.get("project_name")
        if pn:
            qs = qs.filter(project_name__iexact=pn.strip())
        rows = list(qs)
        rows.sort(
            key=lambda r: (r.project_name.lower(), month_year_sort_key(r.month_year))
        )
        return Response(ProjectManpowerSerializer(rows, many=True).data)

    @swagger_auto_schema(auto_schema=None)
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(
        tags=swagger_tags,
        operation_summary="Manpower: dashboard chart data (GET)",
        operation_id="manpower_dashboard",
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
                        example=["Jan-23", "Feb-23", "Mar-23"],
                    ),
                    "planned_manpower": openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(type=openapi.TYPE_INTEGER),
                    ),
                    "actual_manpower": openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(type=openapi.TYPE_INTEGER),
                    ),
                    "planned_mh_cumulative": openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(type=openapi.TYPE_NUMBER),
                    ),
                    "actual_mh_cumulative": openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(type=openapi.TYPE_NUMBER),
                    ),
                    "manpower_efficiency": openapi.Schema(
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
        rows = list(
            ProjectManpower.objects.filter(project_name__iexact=pn).order_by(
                "month_year"
            )
        )
        rows.sort(key=lambda r: month_year_sort_key(r.month_year))

        months = [dashboard_month_label(r.month_year) for r in rows]
        planned_mp = [r.planned_manpower for r in rows]
        actual_mp = [r.actual_manpower for r in rows]
        planned_c = [round(r.planned_mh_cumulative, 2) for r in rows]
        actual_c = [round(r.actual_mh_cumulative, 2) for r in rows]
        eff = [
            None if r.planned_manpower == 0
            else round(r.actual_manpower / r.planned_manpower, 4)
            for r in rows
        ]
        below = [r.actual_manpower < r.planned_manpower for r in rows]

        return Response(
            {
                "months": months,
                "planned_manpower": planned_mp,
                "actual_manpower": actual_mp,
                "planned_mh_cumulative": planned_c,
                "actual_mh_cumulative": actual_c,
                "manpower_efficiency": eff,
                "actual_below_planned": below,
            }
        )
