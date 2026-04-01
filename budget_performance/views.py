"""
Budget vs Cost Performance API (EVM).

POST: accept inputs, compute CPI/EAC/ETG/VAC/CV in serializer.create(), persist, return JSON.
GET: list all records for dashboard consumption.
"""

from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status, viewsets
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import BudgetCostPerformance
from .serializers import (
    BudgetCostPerformanceInputSerializer,
    BudgetCostPerformanceSerializer,
)

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
    - GET  /api/budget-performance/  — list all records (newest first)
    """

    queryset = BudgetCostPerformance.objects.all()
    serializer_class = BudgetCostPerformanceSerializer
    permission_classes = [AllowAny]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        qs = BudgetCostPerformance.objects.all()
        pn = self.request.query_params.get("project_name")
        if pn:
            qs = qs.filter(project_name__iexact=pn.strip())
        return qs.order_by("-created_at")

    @swagger_auto_schema(
        operation_summary="Create budget vs cost performance (EVM)",
        operation_description=(
            "Body: **project_name**, **budget_at_completion** (BAC), "
            "**earned_value** (BCWP), **actual_cost** (ACWP). "
            "Optional aliases: bac, bcwp, acwp."
        ),
        request_body=_BUDGET_PERFORMANCE_POST_SCHEMA,
        responses={201: openapi.Response("Calculated metrics", BudgetCostPerformanceSerializer)},
    )
    def create(self, request, *args, **kwargs):
        """
        Validate input-only fields; calculations run in BudgetCostPerformanceInputSerializer.create().
        """
        input_serializer = BudgetCostPerformanceInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        instance = input_serializer.save()
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
