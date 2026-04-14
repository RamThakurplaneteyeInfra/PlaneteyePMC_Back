"""
Cash-in vs cash-out API: monthly plan/actual, cumulatives, dashboard for charts.
"""

from django.core.cache import cache
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
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


class CashFlowPagination(PageNumberPagination):
    """Pagination for cash flow records."""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100

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
    pagination_class = CashFlowPagination
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        """
        Optimized queryset with action-specific logic.
        """
        # Use .only() to fetch only required fields for performance
        qs = CashFlow.objects.only(
            'id', 'project_name', 'month_year',
            'cash_in_monthly_plan', 'cash_in_monthly_actual',
            'cash_out_monthly_plan', 'cash_out_monthly_actual',
            'actual_cost_monthly',
            'cash_in_cumulative_plan', 'cash_in_cumulative_actual',
            'cash_out_cumulative_plan', 'cash_out_cumulative_actual',
            'actual_cost_cumulative',
            'created_at'
        )

        # Apply different logic based on action
        if self.action == 'list':
            # For list view: apply filtering and database-level sorting
            pn = self.request.query_params.get("project_name")
            if pn:
                qs = qs.filter(project_name__iexact=pn.strip())

            # Use database-level ordering to match original chronological sorting
            # Extract year and month from "Mon-YYYY" format for proper ordering
            return qs.extra(
                select={
                    'sort_year': "CAST(SUBSTR(month_year, 5, 4) AS INTEGER)",
                    'sort_month': "CASE SUBSTR(month_year, 1, 3) "
                                "WHEN 'Jan' THEN 1 WHEN 'Feb' THEN 2 WHEN 'Mar' THEN 3 "
                                "WHEN 'Apr' THEN 4 WHEN 'May' THEN 5 WHEN 'Jun' THEN 6 "
                                "WHEN 'Jul' THEN 7 WHEN 'Aug' THEN 8 WHEN 'Sep' THEN 9 "
                                "WHEN 'Oct' THEN 10 WHEN 'Nov' THEN 11 WHEN 'Dec' THEN 12 END"
                }
            ).order_by('project_name', 'sort_year', 'sort_month')
        else:
            # For retrieve/detail view: return full queryset without filtering
            return qs

    def _get_cache_key(self, request):
        """Generate cache key based on project_name filter."""
        pn = request.query_params.get("project_name", "").strip()
        return f"cashflow_list:{pn or 'all'}"

    def _get_dashboard_cache_key(self, project_name):
        """Generate cache key for dashboard endpoint."""
        return f"cashflow_dashboard:{project_name}"

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

        # Cache invalidation: clear relevant cache keys after creation
        project_name = ser.validated_data.get('project_name', '').strip()
        cache.delete(f"cashflow_list:{project_name or 'all'}")
        cache.delete(f"cashflow_dashboard:{project_name}")
        cache.delete("cashflow_list:all")  # Clear general cache too

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
            openapi.Parameter(
                'page',
                openapi.IN_QUERY,
                description='Page number for pagination',
                type=openapi.TYPE_INTEGER,
                required=False
            ),
            openapi.Parameter(
                'page_size',
                openapi.IN_QUERY,
                description='Number of records per page (max 100)',
                type=openapi.TYPE_INTEGER,
                required=False
            ),
        ],
        responses={200: CashFlowSerializer(many=True)},
    )
    @method_decorator(cache_page(300))  # 5 minutes cache
    def list(self, request, *args, **kwargs):
        """
        Cached list endpoint with pagination.
        Uses database-level sorting instead of Python sorting.
        """
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

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

        # Check cache first
        cache_key = self._get_dashboard_cache_key(pn)
        cached_response = cache.get(cache_key)
        if cached_response is not None:
            return Response(cached_response)

        # Optimized query: use database ordering and only required fields
        rows = list(CashFlow.objects.filter(project_name__iexact=pn).only(
            'month_year',
            'cash_in_monthly_plan', 'cash_in_monthly_actual',
            'cash_out_monthly_plan', 'cash_out_monthly_actual',
            'actual_cost_monthly',
            'cash_in_cumulative_plan', 'cash_in_cumulative_actual',
            'cash_out_cumulative_plan', 'cash_out_cumulative_actual',
            'actual_cost_cumulative'
        ).extra(
            select={
                'sort_year': "CAST(SUBSTR(month_year, 5, 4) AS INTEGER)",
                'sort_month': "CASE SUBSTR(month_year, 1, 3) "
                            "WHEN 'Jan' THEN 1 WHEN 'Feb' THEN 2 WHEN 'Mar' THEN 3 "
                            "WHEN 'Apr' THEN 4 WHEN 'May' THEN 5 WHEN 'Jun' THEN 6 "
                            "WHEN 'Jul' THEN 7 WHEN 'Aug' THEN 8 WHEN 'Sep' THEN 9 "
                            "WHEN 'Oct' THEN 10 WHEN 'Nov' THEN 11 WHEN 'Dec' THEN 12 END"
            }
        ).order_by('sort_year', 'sort_month'))

        # Optimized rounding: avoid repeated float() conversions
        # Since values are stored as Decimal, convert directly to float once
        def to_float(value):
            """Convert Decimal to float for JSON serialization."""
            return float(value) if value is not None else 0.0

        months = [dashboard_month_label(r.month_year) for r in rows]
        body = {
            "months": months,
            "cash_in_monthly_plan": [round(to_float(r.cash_in_monthly_plan), 2) for r in rows],
            "cash_in_monthly_actual": [round(to_float(r.cash_in_monthly_actual), 2) for r in rows],
            "cash_out_monthly_plan": [round(to_float(r.cash_out_monthly_plan), 2) for r in rows],
            "cash_out_monthly_actual": [round(to_float(r.cash_out_monthly_actual), 2) for r in rows],
            "actual_cost_monthly": [round(to_float(r.actual_cost_monthly), 2) for r in rows],
            "cash_in_cumulative_plan": [round(to_float(r.cash_in_cumulative_plan), 2) for r in rows],
            "cash_in_cumulative_actual": [round(to_float(r.cash_in_cumulative_actual), 2) for r in rows],
            "cash_out_cumulative_plan": [round(to_float(r.cash_out_cumulative_plan), 2) for r in rows],
            "cash_out_cumulative_actual": [round(to_float(r.cash_out_cumulative_actual), 2) for r in rows],
            "actual_cost_cumulative": [round(to_float(r.actual_cost_cumulative), 2) for r in rows],
            "profit_cumulative_actual": [
                round(to_float(r.cash_in_cumulative_actual - r.cash_out_cumulative_actual), 2)
                for r in rows
            ],
            "cash_out_exceeds_cash_in_actual": [
                to_float(r.cash_out_monthly_actual) > to_float(r.cash_in_monthly_actual)
                for r in rows
            ],
        }

        # Cache the response for 5 minutes
        cache.set(cache_key, body, 300)

        return Response(body)
