"""
Manpower & man-hours API: monthly planned/actual, MH, cumulative MH, dashboard series.
"""

from django.core.cache import cache
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.pagination import PageNumberPagination
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
    pagination_class = PageNumberPagination

    def get_queryset(self):
        qs = ProjectManpower.objects.only(
            "id", "project_name", "month_year", "planned_manpower", "actual_manpower",
            "working_hours_per_day", "working_days_per_month", "planned_mh", "actual_mh",
            "planned_mh_cumulative", "actual_mh_cumulative", "created_at"
        )
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
    def perform_create(self, serializer):
        super().perform_create(serializer)
        # Cache invalidation (safe for both LocMemCache and Redis backends)
        try:
            cache.delete_pattern("manpower_list:*")
            cache.delete_pattern("manpower_dashboard:*")
        except AttributeError:
            # LocMemCache doesn't support delete_pattern; clear all cache
            cache.clear()

    def create(self, request, *args, **kwargs):
        ser = ProjectManpowerInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        self.perform_create(ser)
        return Response(
            ProjectManpowerSerializer(ser.instance).data,
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
        cache_key = f"manpower_list:{request.get_full_path()}"
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

        cache_key = f"manpower_dashboard:{pn}"
        data = cache.get(cache_key)
        if data is not None:
            return Response(data)

        rows = ProjectManpower.objects.filter(project_name__iexact=pn).only(
            "month_year", "planned_manpower", "actual_manpower",
            "planned_mh_cumulative", "actual_mh_cumulative"
        ).order_by("month_year")

        # Pre-allocate lists
        months = []
        planned_manpower = []
        actual_manpower = []
        planned_mh_cumulative = []
        actual_mh_cumulative = []
        manpower_efficiency = []
        actual_below_planned = []

        for r in rows:
            months.append(dashboard_month_label(r.month_year))
            planned_manpower.append(r.planned_manpower)
            actual_manpower.append(r.actual_manpower)
            planned_mh_cumulative.append(round(r.planned_mh_cumulative, 2))
            actual_mh_cumulative.append(round(r.actual_mh_cumulative, 2))
            if r.planned_manpower == 0:
                manpower_efficiency.append(None)
            else:
                manpower_efficiency.append(round(r.actual_manpower / r.planned_manpower, 4))
            actual_below_planned.append(r.actual_manpower < r.planned_manpower)

        data = {
            "months": months,
            "planned_manpower": planned_manpower,
            "actual_manpower": actual_manpower,
            "planned_mh_cumulative": planned_mh_cumulative,
            "actual_mh_cumulative": actual_mh_cumulative,
            "manpower_efficiency": manpower_efficiency,
            "actual_below_planned": actual_below_planned,
        }

        cache.set(cache_key, data, 300)  # 5 minutes
        return Response(data)
