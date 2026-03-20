"""
Cash-in vs cash-out API: monthly plan/actual, cumulatives, dashboard for charts.
"""

from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import CashFlow
from .serializers import (
    CashFlowInputSerializer,
    CashFlowSerializer,
    dashboard_month_label,
    month_year_sort_key,
)

swagger_tags = ["Cash flow — in vs out"]

_CASHFLOW_POST_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    required=[
        "project_name",
        "month_year",
        "cash_in_monthly_plan",
        "cash_in_monthly_actual",
        "cash_out_monthly_plan",
        "cash_out_monthly_actual",
        "actual_cost_monthly",
    ],
    properties={
        "project_name": openapi.Schema(
            type=openapi.TYPE_STRING,
            description="Project name",
            example="Project Alpha",
        ),
        "month_year": openapi.Schema(
            type=openapi.TYPE_STRING,
            description='Calendar month label, format "Jan-2023"',
            example="Jan-2023",
        ),
        "cash_in_monthly_plan": openapi.Schema(
            type=openapi.TYPE_NUMBER,
            description="Planned cash-in for the month (≥ 0)",
            example=100000.0,
        ),
        "cash_in_monthly_actual": openapi.Schema(
            type=openapi.TYPE_NUMBER,
            description="Actual cash-in for the month (≥ 0)",
            example=95000.0,
        ),
        "cash_out_monthly_plan": openapi.Schema(
            type=openapi.TYPE_NUMBER,
            description="Planned cash-out for the month (≥ 0)",
            example=80000.0,
        ),
        "cash_out_monthly_actual": openapi.Schema(
            type=openapi.TYPE_NUMBER,
            description="Actual cash-out for the month (≥ 0)",
            example=82000.0,
        ),
        "actual_cost_monthly": openapi.Schema(
            type=openapi.TYPE_NUMBER,
            description="Actual cost for the month (≥ 0)",
            example=75000.0,
        ),
    },
)


class CashFlowViewSet(viewsets.ModelViewSet):
    queryset = CashFlow.objects.all()
    serializer_class = CashFlowSerializer
    permission_classes = [AllowAny]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        qs = CashFlow.objects.all()
        pn = self.request.query_params.get("project_name")
        if pn:
            qs = qs.filter(project_name__iexact=pn.strip())
        return qs

    @swagger_auto_schema(
        tags=swagger_tags,
        operation_summary="Cash flow: add monthly row (POST)",
        operation_id="cashflow_create",
        request_body=_CASHFLOW_POST_SCHEMA,
        responses={201: CashFlowSerializer},
    )
    def create(self, request, *args, **kwargs):
        ser = CashFlowInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        instance = ser.save()
        return Response(
            CashFlowSerializer(instance).data,
            status=status.HTTP_201_CREATED,
        )

    @swagger_auto_schema(
        tags=swagger_tags,
        operation_summary="Cash flow: list rows (GET)",
        operation_id="cashflow_list",
        manual_parameters=[
            openapi.Parameter(
                "project_name",
                openapi.IN_QUERY,
                description="Filter by project (optional)",
                type=openapi.TYPE_STRING,
            ),
        ],
        responses={200: CashFlowSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        rows = list(qs)
        rows.sort(
            key=lambda r: (r.project_name.lower(), month_year_sort_key(r.month_year))
        )
        return Response(CashFlowSerializer(rows, many=True).data)

    @swagger_auto_schema(auto_schema=None)
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(
        tags=swagger_tags,
        operation_summary="Cash flow: dashboard (bar + line charts)",
        operation_id="cashflow_dashboard",
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
                description="Parallel arrays by month index",
                properties={
                    "months": openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(type=openapi.TYPE_STRING),
                    ),
                    "cash_in_monthly_plan": openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(type=openapi.TYPE_NUMBER),
                    ),
                    "cash_in_monthly_actual": openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(type=openapi.TYPE_NUMBER),
                    ),
                    "cash_out_monthly_plan": openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(type=openapi.TYPE_NUMBER),
                    ),
                    "cash_out_monthly_actual": openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(type=openapi.TYPE_NUMBER),
                    ),
                    "actual_cost_monthly": openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(type=openapi.TYPE_NUMBER),
                    ),
                    "cash_in_cumulative_plan": openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(type=openapi.TYPE_NUMBER),
                    ),
                    "cash_in_cumulative_actual": openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(type=openapi.TYPE_NUMBER),
                    ),
                    "cash_out_cumulative_plan": openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(type=openapi.TYPE_NUMBER),
                    ),
                    "cash_out_cumulative_actual": openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(type=openapi.TYPE_NUMBER),
                    ),
                    "actual_cost_cumulative": openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(type=openapi.TYPE_NUMBER),
                    ),
                    "profit_cumulative_actual": openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(type=openapi.TYPE_NUMBER),
                        description="cash_in_cumulative_actual − cash_out_cumulative_actual",
                    ),
                    "cash_out_exceeds_cash_in_actual": openapi.Schema(
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
        rows = list(CashFlow.objects.filter(project_name__iexact=pn))
        rows.sort(key=lambda r: month_year_sort_key(r.month_year))

        def rnd(x):
            return round(float(x), 2)

        months = [dashboard_month_label(r.month_year) for r in rows]
        body = {
            "months": months,
            "cash_in_monthly_plan": [rnd(r.cash_in_monthly_plan) for r in rows],
            "cash_in_monthly_actual": [rnd(r.cash_in_monthly_actual) for r in rows],
            "cash_out_monthly_plan": [rnd(r.cash_out_monthly_plan) for r in rows],
            "cash_out_monthly_actual": [rnd(r.cash_out_monthly_actual) for r in rows],
            "actual_cost_monthly": [rnd(r.actual_cost_monthly) for r in rows],
            "cash_in_cumulative_plan": [rnd(r.cash_in_cumulative_plan) for r in rows],
            "cash_in_cumulative_actual": [rnd(r.cash_in_cumulative_actual) for r in rows],
            "cash_out_cumulative_plan": [rnd(r.cash_out_cumulative_plan) for r in rows],
            "cash_out_cumulative_actual": [rnd(r.cash_out_cumulative_actual) for r in rows],
            "actual_cost_cumulative": [rnd(r.actual_cost_cumulative) for r in rows],
            "profit_cumulative_actual": [
                rnd(r.cash_in_cumulative_actual - r.cash_out_cumulative_actual)
                for r in rows
            ],
            "cash_out_exceeds_cash_in_actual": [
                r.cash_out_monthly_actual > r.cash_in_monthly_actual for r in rows
            ],
        }
        return Response(body)
