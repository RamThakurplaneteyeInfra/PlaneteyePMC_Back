"""
Budget vs Cost Performance API (EVM).

POST: accept inputs, compute CPI/EAC/ETG/VAC/CV in serializer.create(), persist, return JSON.
GET: list all records for dashboard consumption (with pagination, caching, and optimizations).
"""

from django.core.cache import cache
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status, viewsets
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import BudgetCostPerformance
from .serializers import (
    BudgetCostPerformanceInputSerializer,
    BudgetCostPerformanceSerializer,
)

class BudgetPerformancePagination(PageNumberPagination):
    """Pagination for budget performance records."""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


_BUDGET_PERFORMANCE_POST_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    required=[
        "project_name",
        "budget_at_completion",
        "earned_value",
        "actual_cost",
    ],
    properties={
        "project_name": openapi.Schema(
            type=openapi.TYPE_STRING, example="Atlas Project"
        ),
        "budget_at_completion": openapi.Schema(
            type=openapi.TYPE_NUMBER,
            description="BAC — budget at completion",
            example=112_000_000,
        ),
        "earned_value": openapi.Schema(
            type=openapi.TYPE_NUMBER,
            description="BCWP — earned value",
            example=17_160_000,
        ),
        "actual_cost": openapi.Schema(
            type=openapi.TYPE_NUMBER,
            description="ACWP — actual cost",
            example=21_360_000,
        ),
    },
)


class BudgetCostPerformanceViewSet(viewsets.ModelViewSet):
    """
    Endpoints:
    - POST /api/budget-performance/  — create and return calculated metrics
    - GET  /api/budget-performance/  — list all records (newest first, paginated, cached)
    - GET  /api/budget-performance/{id}/  — retrieve single record by ID
    """

    queryset = BudgetCostPerformance.objects.all()
    serializer_class = BudgetCostPerformanceSerializer
    permission_classes = [AllowAny]
    pagination_class = BudgetPerformancePagination
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        """
        Optimized queryset with action-specific logic.
        """
        # Use .only() to fetch only required fields for performance
        qs = BudgetCostPerformance.objects.only(
            'id', 'project_name', 'bac', 'bcwp', 'acwp',
            'cpi', 'eac', 'etg', 'vac', 'cv', 'created_at'
        )

        # Apply different logic based on action
        if self.action == 'list':
            # For list view: apply filtering, ordering, and safe limits
            pn = self.request.query_params.get("project_name")
            if pn:
                qs = qs.filter(project_name__iexact=pn.strip())

            # Safe limit to prevent large dataset issues (latest 50 records)
            # Keep ordering by -created_at for dashboard relevance
            return qs.order_by("-created_at")[:50]
        else:
            # For retrieve/detail view: return full queryset without filtering or limits
            # This ensures GET by ID works for any record
            return qs

    def _get_cache_key(self, request):
        """Generate cache key based on project_name filter."""
        pn = request.query_params.get("project_name", "").strip()
        return f"budget_performance_list:{pn or 'all'}"

    @swagger_auto_schema(
        operation_summary="List budget vs cost performance records",
        operation_description=(
            "Returns paginated list of EVM calculations for dashboard. "
            "Results are cached for 5 minutes. Supports project_name filtering."
        ),
        manual_parameters=[
            openapi.Parameter(
                'project_name',
                openapi.IN_QUERY,
                description='Filter by project name (case-insensitive)',
                type=openapi.TYPE_STRING,
                required=False
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
        responses={
            200: openapi.Response(
                "Paginated list of EVM records",
                BudgetCostPerformanceSerializer(many=True)
            )
        },
    )
    @method_decorator(cache_page(300))  # 5 minutes cache
    def list(self, request, *args, **kwargs):
        """
        Cached list endpoint with pagination.
        Returns all calculated records for the dashboard.
        """
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @swagger_auto_schema(
        operation_summary="Create budget vs cost performance (EVM)",
        operation_description=(
            "Body: **project_name**, **budget_at_completion** (BAC), "
            "**earned_value** (BCWP), **actual_cost** (ACWP). "
            "Optional aliases: bac, bcwp, acwp. "
            "Creates cache invalidation for dashboard data."
        ),
        request_body=_BUDGET_PERFORMANCE_POST_SCHEMA,
        responses={201: openapi.Response("Calculated metrics", BudgetCostPerformanceSerializer)},
    )
    def create(self, request, *args, **kwargs):
        """
        Validate input-only fields; calculations run in BudgetCostPerformanceInputSerializer.create().
        Clears relevant cache keys after successful creation.
        """
        input_serializer = BudgetCostPerformanceInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        instance = input_serializer.save()

        # Cache invalidation: clear relevant cache keys
        project_name = input_serializer.validated_data.get('project_name', '').strip()
        cache.delete(f"budget_performance_list:{project_name or 'all'}")
        cache.delete("budget_performance_list:all")  # Clear general cache too

        out = BudgetCostPerformanceSerializer(instance).data
        # Match spec: dashboard JSON without id/created_at on create if desired — spec shows plain object.
        # Strip optional keys for POST response to align with example.
        response_body = {
            "project_name": out["project_name"],
            "bac": out["bac"],
            "bcwp": out["bcwp"],
            "acwp": out["acwp"],
            "cpi": out["cpi"],
            "eac": out["eac"],
            "etg": out["etg"],
            "vac": out["vac"],
            "cv": out["cv"],
        }
        headers = self.get_success_headers(response_body)
        return Response(response_body, status=status.HTTP_201_CREATED, headers=headers)

    def list(self, request, *args, **kwargs):
        """Return all calculated records for the dashboard."""
        queryset = self.filter_queryset(self.get_queryset())
        serializer = BudgetCostPerformanceSerializer(queryset, many=True)
        return Response(serializer.data)
