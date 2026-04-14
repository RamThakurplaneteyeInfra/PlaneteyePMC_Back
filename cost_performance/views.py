"""
Cost performance EVM API: monthly BCWS/BCWP/ACWP/FCST → EAC, CV, SV (+ CPI, VAC).
"""

import hashlib

from django.core.cache import cache
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import ProjectCostPerformance
from .serializers import (
    EVMDashboardInputSerializer,
    EVMDashboardOutputSerializer,
    dashboard_month_label,
    month_year_sort_key,
    ProjectCostPerformanceInputSerializer,
    ProjectCostPerformanceSerializer,
)

swagger_tags = ["Cost performance (EVM)"]

_POST_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    required=[
        "project_name",
        "month_year",
        "bcws",
        "bcwp",
        "acwp",
        "fcst",
    ],
    properties={
        "project_name": openapi.Schema(type=openapi.TYPE_STRING, example="Alpha"),
        "month_year": openapi.Schema(
            type=openapi.TYPE_STRING,
            description='e.g. "Jan-2023"',
            example="Jan-2023",
        ),
        "bcws": openapi.Schema(
            type=openapi.TYPE_NUMBER,
            description="BCWS — planned cost (budgeted cost of work scheduled)",
            example=500000.0,
        ),
        "bcwp": openapi.Schema(
            type=openapi.TYPE_NUMBER,
            description="BCWP — earned value (budgeted cost of work performed)",
            example=480000.0,
        ),
        "acwp": openapi.Schema(
            type=openapi.TYPE_NUMBER,
            description="ACWP — actual cost",
            example=520000.0,
        ),
        "fcst": openapi.Schema(
            type=openapi.TYPE_NUMBER,
            description="FCST — forecast remaining work cost",
            example=200000.0,
        ),
        "bac": openapi.Schema(
            type=openapi.TYPE_NUMBER,
            description="Optional BAC for VAC = BAC − EAC",
            example=1000000.0,
        ),
    },
)


class ProjectCostPerformanceViewSet(viewsets.ModelViewSet):
    queryset = ProjectCostPerformance.objects.all()
    serializer_class = ProjectCostPerformanceSerializer
    permission_classes = [AllowAny]
    http_method_names = ["get", "post", "head", "options"]
    pagination_class = PageNumberPagination

    def get_queryset(self):
        qs = ProjectCostPerformance.objects.select_related("project").only(
            "id", "project__name", "month_year", "bcws", "bcwp", "acwp", "fcst", "eac", "cv", "sv", "cpi", "vac"
        )
        pn = self.request.query_params.get("project_name")
        if pn:
            qs = qs.filter(project__name__icontains=pn.strip())
        return qs

    @swagger_auto_schema(
        tags=swagger_tags,
        operation_summary="Cost performance: add monthly EVM row (POST)",
        operation_id="cost_performance_create",
        operation_description=(
            "**EAC** = ACWP + FCST (final cost estimate). "
            "**CV** = BCWP − ACWP. **SV** = BCWP − BCWS. "
            "Optional **CPI** = BCWP/ACWP; **VAC** = BAC − EAC if `bac` sent."
        ),
        request_body=_POST_SCHEMA,
        responses={201: ProjectCostPerformanceSerializer},
    )
    def create(self, request, *args, **kwargs):
        ser = ProjectCostPerformanceInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        instance = ser.save()

        # Cache invalidation
        pn = instance.project.name
        cache.delete(f"cost_performance_list:all")
        cache.delete(f"cost_performance_list:{pn}")
        cache.delete(f"cost_performance_dashboard:{pn}")

        return Response(
            ProjectCostPerformanceSerializer(instance).data,
            status=status.HTTP_201_CREATED,
        )

    @swagger_auto_schema(
        tags=swagger_tags,
        operation_summary="Cost performance: list (GET)",
        operation_id="cost_performance_list",
        manual_parameters=[
            openapi.Parameter(
                "project_name",
                openapi.IN_QUERY,
                description="Filter by project",
                type=openapi.TYPE_STRING,
            ),
        ],
        responses={200: ProjectCostPerformanceSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        pn = self.request.query_params.get("project_name")
        cache_key = f"cost_performance_list:{pn}" if pn else "cost_performance_list:all"
        data = cache.get(cache_key)
        if data is not None:
            return Response(data)

        qs = self.get_queryset().order_by("project__name", "month_year")
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            data = self.get_paginated_response(serializer.data).data
        else:
            serializer = self.get_serializer(qs, many=True)
            data = serializer.data

        cache.set(cache_key, data, 300)  # 5 minutes
        return Response(data)

    @swagger_auto_schema(auto_schema=None)
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(
        tags=swagger_tags,
        operation_summary="Cost performance: dashboard series (GET)",
        operation_id="cost_performance_dashboard",
        manual_parameters=[
            openapi.Parameter(
                "project_name",
                openapi.IN_QUERY,
                required=True,
                type=openapi.TYPE_STRING,
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
                    "bcws": openapi.Schema(type=openapi.TYPE_ARRAY, items=openapi.Schema(type=openapi.TYPE_NUMBER)),
                    "bcwp": openapi.Schema(type=openapi.TYPE_ARRAY, items=openapi.Schema(type=openapi.TYPE_NUMBER)),
                    "acwp": openapi.Schema(type=openapi.TYPE_ARRAY, items=openapi.Schema(type=openapi.TYPE_NUMBER)),
                    "fcst": openapi.Schema(type=openapi.TYPE_ARRAY, items=openapi.Schema(type=openapi.TYPE_NUMBER)),
                    "eac": openapi.Schema(type=openapi.TYPE_ARRAY, items=openapi.Schema(type=openapi.TYPE_NUMBER)),
                    "cv": openapi.Schema(type=openapi.TYPE_ARRAY, items=openapi.Schema(type=openapi.TYPE_NUMBER)),
                    "sv": openapi.Schema(type=openapi.TYPE_ARRAY, items=openapi.Schema(type=openapi.TYPE_NUMBER)),
                    "cpi": openapi.Schema(type=openapi.TYPE_ARRAY, items=openapi.Schema(type=openapi.TYPE_NUMBER)),
                    "vac": openapi.Schema(type=openapi.TYPE_ARRAY, items=openapi.Schema(type=openapi.TYPE_NUMBER)),
                    "over_budget_cost": openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(type=openapi.TYPE_BOOLEAN),
                    ),
                    "behind_schedule": openapi.Schema(
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

        cache_key = f"cost_performance_dashboard:{pn}"
        data = cache.get(cache_key)
        if data is not None:
            return Response(data)

        rows = ProjectCostPerformance.objects.filter(project__name__icontains=pn).only(
            "month_year", "bcws", "bcwp", "acwp", "fcst", "eac", "cv", "sv", "cpi", "vac"
        ).order_by("month_year")

        def r4(x):
            return round(float(x), 4) if x is not None else None

        data = {
            "months": [dashboard_month_label(r.month_year) for r in rows],
            "bcws": [r4(r.bcws) for r in rows],
            "bcwp": [r4(r.bcwp) for r in rows],
            "acwp": [r4(r.acwp) for r in rows],
            "fcst": [r4(r.fcst) for r in rows],
            "eac": [r4(r.eac) for r in rows],
            "cv": [r4(r.cv) for r in rows],
            "sv": [r4(r.sv) for r in rows],
            "cpi": [r4(r.cpi) if r.cpi is not None else None for r in rows],
            "vac": [r4(r.vac) if r.vac is not None else None for r in rows],
            "over_budget_cost": [r.cv < 0 for r in rows],
            "behind_schedule": [r.sv < 0 for r in rows],
        }

        cache.set(cache_key, data, 300)  # 5 minutes
        return Response(data)

    # ========================================
    # New EVM Dashboard API (Enhanced)
    # ========================================

    @swagger_auto_schema(
        tags=swagger_tags,
        operation_summary="EVM Dashboard: compute metrics from monthly data",
        operation_id="evm_dashboard_compute",
        operation_description=(
            """
            Compute complete EVM metrics from project data.
            
            **Input Format:**
            {
                "project_name": "Project Alpha",
                "bac": 1000000,
                "monthly_data": [
                    {
                        "month": "Jan-2022",
                        "bcws": 100000,
                        "percent_complete": 50,  // OR use bcwp directly
                        "bcwp": 50000,            // OR use percent_complete
                        "ac": 55000
                    }
                ]
            }
            
            **Formulas:**
            - BCWP = percent_complete * BAC (if not provided)
            - CV = BCWP - AC
            - CPI = BCWP / AC (handle divide by zero)
            - EAC = BAC / CPI
            - ETC = EAC - AC
            - Status: under_budget (CPI > 1), on_budget (CPI = 1), over_budget (CPI < 1)
            """
        ),
        request_body=EVMDashboardInputSerializer,
        responses={200: EVMDashboardOutputSerializer},
    )
    @action(detail=False, methods=["post"], url_path="evm-dashboard")
    def evm_dashboard(self, request):
        """
        Compute EVM dashboard metrics from monthly data.

        Accepts:
        - BAC (Budget at Completion)
        - Monthly data with BCWS, percentComplete/BCWP, AC

        Returns:
        - Summary (BCWP, AC, CV, CPI, Status, EAC, ETC)
        - Monthly data (all computed metrics per month)
        - Cumulative data (running totals)
        """
        ser = EVMDashboardInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        # Generate cache key from request data
        request_hash = hashlib.md5(str(request.data).encode()).hexdigest()
        cache_key = f"cost_performance_evm_dashboard:{request_hash}"
        data = cache.get(cache_key)
        if data is not None:
            return Response(data)
        
        project_name = ser.validated_data['project_name']
        bac = float(ser.validated_data['bac'])
        monthly_data = ser.validated_data['monthly_data']
        
        # Sort monthly data by month
        sorted_data = sorted(
            monthly_data,
            key=lambda x: month_year_sort_key(x['month'])
        )
        
        # Process each month and compute EVM metrics
        processed_monthly = []
        cumulative_bcws = 0
        cumulative_bcwp = 0
        cumulative_ac = 0
        cumulative_cv = 0
        
        for item in sorted_data:
            month = item['month']
            bcws = float(item.get('bcws', 0))
            ac = float(item.get('ac', 0))
            
            # Compute BCWP from percent_complete or use provided value
            if item.get('bcwp') is not None:
                bcwp = float(item['bcwp'])
            elif item.get('percent_complete') is not None:
                percent = float(item['percent_complete']) / 100  # Convert percentage to decimal
                bcwp = round(percent * bac, 2)
            else:
                bcwp = 0
            
            # Compute Cost Variance (CV)
            cv = round(bcwp - ac, 2)
            
            # Compute Cost Performance Index (CPI)
            if ac > 0:
                cpi = round(bcwp / ac, 4)
            else:
                cpi = None
            
            # Determine status based on CPI
            if cpi is None:
                status_val = "unknown"
            elif cpi > 1:
                status_val = "under_budget"
            elif cpi == 1:
                status_val = "on_budget"
            else:
                status_val = "over_budget"
            
            # Compute forecast (FCST) - remaining work cost estimate
            # FCST = (BAC - BCWP) / CPI if CPI > 0, else remaining budget
            if cpi and cpi > 0:
                remaining_work = bac - bcwp
                fcst = round(remaining_work / cpi, 2) if remaining_work > 0 else 0
            else:
                fcst = None
            
            # Update cumulative values
            cumulative_bcws += bcws
            cumulative_bcwp += bcwp
            cumulative_ac += ac
            cumulative_cv += cv
            
            processed_monthly.append({
                'month': dashboard_month_label(month),
                'bcws': round(bcws, 2),
                'bcwp': round(bcwp, 2),
                'ac': round(ac, 2),
                'cv': cv,
                'cpi': cpi,
                'status': status_val,
                'fcst': fcst,
            })
        
        # Compute cumulative data
        cumulative_data = []
        cum_bcws = 0
        cum_bcwp = 0
        cum_ac = 0
        
        for item in sorted_data:
            month = item['month']
            bcws = float(item.get('bcws', 0))
            
            if item.get('bcwp') is not None:
                bcwp = float(item['bcwp'])
            elif item.get('percent_complete') is not None:
                percent = float(item['percent_complete']) / 100
                bcwp = round(percent * bac, 2)
            else:
                bcwp = 0
            
            ac = float(item.get('ac', 0))
            
            cum_bcws += bcws
            cum_bcwp += bcwp
            cum_ac += ac
            
            # Cumulative CV
            cum_cv = cum_bcwp - cum_ac
            
            # Cumulative CPI
            if cum_ac > 0:
                cum_cpi = round(cum_bcwp / cum_ac, 4)
            else:
                cum_cpi = None
            
            cumulative_data.append({
                'month': dashboard_month_label(month),
                'cumulative_bcws': round(cum_bcws, 2),
                'cumulative_bcwp': round(cum_bcwp, 2),
                'cumulative_ac': round(cum_ac, 2),
                'cumulative_cv': round(cum_cv, 2),
                'cumulative_cpi': cum_cpi,
            })
        
        # Compute final summary (using latest month's cumulative values)
        if cumulative_data:
            final_cum = cumulative_data[-1]
            final_bcwp = final_cum['cumulative_bcwp']
            final_ac = final_cum['cumulative_ac']
            final_cv = final_cum['cumulative_cv']
            final_cpi = final_cum['cumulative_cpi']
        else:
            final_bcwp = 0
            final_ac = 0
            final_cv = 0
            final_cpi = None
        
        # Compute EAC and ETC
        if final_cpi and final_cpi > 0:
            eac = round(bac / final_cpi, 2)
            etc = round(eac - final_ac, 2)
        else:
            eac = bac  # If no CPI, assume EAC = BAC
            etc = round(eac - final_ac, 2)
        
        # Final status
        if final_cpi is None:
            final_status = "unknown"
        elif final_cpi > 1:
            final_status = "under_budget"
        elif final_cpi == 1:
            final_status = "on_budget"
        else:
            final_status = "over_budget"
        
        summary = {
            'bcwp': final_bcwp,
            'ac': final_ac,
            'cv': final_cv,
            'cpi': final_cpi,
            'status': final_status,
            'eac': eac,
            'etc': etc,
        }
        
        response_data = {
            'project_name': project_name,
            'bac': bac,
            'summary': summary,
            'monthly': processed_monthly,
            'cumulative': cumulative_data,
        }

        cache.set(cache_key, response_data, 300)  # 5 minutes
        return Response(response_data)
