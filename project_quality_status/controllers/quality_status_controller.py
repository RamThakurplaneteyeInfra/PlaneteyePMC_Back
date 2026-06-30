"""
Project Quality Status Controller (ViewSet).

  POST   /api/project-quality/
  GET    /api/project-quality/
  GET    /api/project-quality/{id}/
  PUT    /api/project-quality/{id}/
  PATCH  /api/project-quality/{id}/
  DELETE /api/project-quality/{id}/
  GET    /api/project-quality/project/{projectName}/              (dashboard — latest month)
  GET    /api/project-quality/project/{projectName}/month/{m}/year/{y}/
  GET    /api/project-quality/project/{projectName}/year/{y}/summary/
"""

import logging

from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Sum, Value
from django.db.models.functions import Coalesce
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from accounts.permissions import IsAuthenticatedProjectRBAC
from accounts.rbac import RBACDomain
from accounts.rbac_checks import (
    apply_project_rbac_to_queryset,
    enforce_instance_write,
    enforce_project_access_by_name,
    enforce_project_write_by_name,
)
from rest_framework.response import Response

from ..models.project_quality_status import ProjectQualityStatus
from .quality_metrics import metrics_from_counts, monthly_response, dashboard_response
from .quality_status_serializer import ProjectQualityStatusSerializer

logger = logging.getLogger(__name__)

_CACHE_KEY_LIST = "project_quality_status_list"
_CACHE_TIMEOUT = 300

_SNAKE_TO_CAMEL = {
    "project_name": "projectName",
    "tests_required": "tests_required",
    "tests_conducted": "tests_conducted",
    "tests_passed": "tests_passed",
    "tests_failed": "tests_failed",
    "total_tests_conducted": "tests_conducted",
    "total_tests_passed": "tests_passed",
    "totalTestsConducted": "tests_conducted",
    "totalTestsPassed": "tests_passed",
}

_READ_ONLY = {
    "shortfall",
    "quality_performance",
    "pass_rate",
    "fail_rate",
    "variance",
    "performancePercentage",
    "qualityStatus",
    "failedTests",
    "totalTestsConducted",
    "totalTestsPassed",
    "project_name",
    "id",
    "created_at",
    "updated_at",
}


def _normalize_payload(data: dict) -> dict:
    if hasattr(data, "copy"):
        data = data.copy()
    else:
        data = dict(data)
    return {_SNAKE_TO_CAMEL.get(k, k): v for k, v in data.items()}


def _aggregate_yearly(queryset) -> dict:
    """SUM monthly counts, then compute KPIs dynamically."""
    agg = queryset.aggregate(
        tests_required=Coalesce(Sum("tests_required"), Value(0)),
        tests_conducted=Coalesce(Sum("tests_conducted"), Value(0)),
        tests_passed=Coalesce(Sum("tests_passed"), Value(0)),
        tests_failed=Coalesce(Sum("tests_failed"), Value(0)),
    )
    return metrics_from_counts(
        agg["tests_required"],
        agg["tests_conducted"],
        agg["tests_passed"],
        agg["tests_failed"],
        include_rates=True,
    )


class QualityStatusPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


_PQS_POST_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    required=["project_name", "month", "year"],
    properties={
        "project_name": openapi.Schema(type=openapi.TYPE_STRING, example="Thane Project"),
        "month": openapi.Schema(type=openapi.TYPE_INTEGER, example=5),
        "year": openapi.Schema(type=openapi.TYPE_INTEGER, example=2026),
        "tests_required": openapi.Schema(type=openapi.TYPE_INTEGER, example=120),
        "tests_conducted": openapi.Schema(type=openapi.TYPE_INTEGER, example=100),
        "tests_passed": openapi.Schema(type=openapi.TYPE_INTEGER, example=95),
        "tests_failed": openapi.Schema(type=openapi.TYPE_INTEGER, example=5),
    },
)

_PQS_RESPONSE_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    properties={
        "success": openapi.Schema(type=openapi.TYPE_BOOLEAN, example=True),
        "message": openapi.Schema(type=openapi.TYPE_STRING),
        "data": openapi.Schema(type=openapi.TYPE_OBJECT),
    },
)


class ProjectQualityStatusViewSet(viewsets.ModelViewSet):
    """
    Monthly Project Quality Status ViewSet.

    One record per (projectName, month, year).
    shortfall, quality_performance, pass_rate, and fail_rate are computed on read.
    """

    queryset = ProjectQualityStatus.objects.all()
    serializer_class = ProjectQualityStatusSerializer
    pagination_class = QualityStatusPagination
    lookup_value_regex = r"\d+"
    permission_classes = [IsAuthenticatedProjectRBAC]
    rbac_domain = RBACDomain.QAQC

    def get_queryset(self):
        qs = ProjectQualityStatus.objects.all()

        project_name = self.request.query_params.get("project_name")
        if project_name:
            qs = qs.filter(projectName__icontains=project_name.strip())

        year = self.request.query_params.get("year")
        if year:
            try:
                qs = qs.filter(year=int(year))
            except ValueError:
                pass

        month = self.request.query_params.get("month")
        if month:
            try:
                qs = qs.filter(month=int(month))
            except ValueError:
                pass

        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(projectName__icontains=search.strip())

        return apply_project_rbac_to_queryset(qs, self.request, "projectName").order_by(
            "projectName", "year", "month"
        )

    def _invalidate_cache(self):
        cache.delete(_CACHE_KEY_LIST)

    def _success(self, message: str, data, http_status=status.HTTP_200_OK):
        return Response(
            {"success": True, "message": message, "data": data},
            status=http_status,
        )

    def _error(self, message: str, errors=None, http_status=status.HTTP_400_BAD_REQUEST):
        payload = {"success": False, "message": message}
        if errors is not None:
            payload["errors"] = errors
        return Response(payload, status=http_status)

    def _find_monthly_record(self, project_name: str, month: int, year: int):
        return ProjectQualityStatus.objects.filter(
            projectName__iexact=project_name.strip(),
            month=month,
            year=year,
        ).first()

    def _upsert_from_payload(self, payload: dict):
        project_name = str(payload.get("projectName", "")).strip()
        month = payload.get("month")
        year = payload.get("year")

        existing = None
        if project_name and month is not None and year is not None:
            existing = self._find_monthly_record(project_name, int(month), int(year))

        if existing is not None:
            serializer = ProjectQualityStatusSerializer(existing, data=payload)
        else:
            serializer = ProjectQualityStatusSerializer(data=payload)

        return serializer, existing

    @swagger_auto_schema(
        operation_summary="Create Project Quality Status Record",
        request_body=_PQS_POST_SCHEMA,
        responses={201: openapi.Response("Created", _PQS_RESPONSE_SCHEMA), 400: "Validation error"},
        tags=["Project Quality Status"],
    )
    def create(self, request, *args, **kwargs):
        """Create or update a monthly record (upsert by projectName + month + year)."""
        payload = {
            k: v
            for k, v in _normalize_payload(request.data).items()
            if k not in _READ_ONLY
        }

        serializer, existing = self._upsert_from_payload(payload)

        if not serializer.is_valid():
            return self._error("Validation failed", errors=serializer.errors)

        project_name = payload.get("projectName") or payload.get("project_name")
        enforce_project_write_by_name(request.user, project_name, RBACDomain.QAQC)

        try:
            instance = serializer.save()
        except DjangoValidationError as exc:
            return self._error("Validation failed", errors=exc.message_dict)
        except Exception as exc:
            logger.error(f"ProjectQualityStatus create error: {exc}")
            return self._error(
                "Failed to save quality status record",
                errors=str(exc),
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        self._invalidate_cache()

        http_status = status.HTTP_200_OK if existing else status.HTTP_201_CREATED
        message = (
            "Project quality status updated successfully"
            if existing
            else "Project quality status saved successfully"
        )
        return self._success(
            message,
            ProjectQualityStatusSerializer(instance).data,
            http_status=http_status,
        )

    @swagger_auto_schema(
        operation_summary="List Project Quality Status Records",
        manual_parameters=[
            openapi.Parameter("project_name", openapi.IN_QUERY, type=openapi.TYPE_STRING, required=False),
            openapi.Parameter("month", openapi.IN_QUERY, type=openapi.TYPE_INTEGER, required=False),
            openapi.Parameter("year", openapi.IN_QUERY, type=openapi.TYPE_INTEGER, required=False),
            openapi.Parameter("search", openapi.IN_QUERY, type=openapi.TYPE_STRING, required=False),
        ],
        responses={200: openapi.Response("OK", _PQS_RESPONSE_SCHEMA)},
        tags=["Project Quality Status"],
    )
    def list(self, request, *args, **kwargs):
        has_filters = any(
            request.query_params.get(k)
            for k in ("project_name", "month", "year", "search")
        )
        page_param = request.query_params.get("page", "1")
        use_cache = not has_filters and page_param == "1"

        if use_cache:
            cached = cache.get(_CACHE_KEY_LIST)
            if cached is not None:
                return Response(cached)

        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = ProjectQualityStatusSerializer(page, many=True)
            paginated = self.get_paginated_response(serializer.data)
            payload = {
                "success": True,
                "message": "Project quality status records retrieved successfully",
                "data": paginated.data,
            }
            if use_cache:
                cache.set(_CACHE_KEY_LIST, payload, _CACHE_TIMEOUT)
            return Response(payload)

        serializer = ProjectQualityStatusSerializer(queryset, many=True)
        payload = {
            "success": True,
            "message": "Project quality status records retrieved successfully",
            "data": serializer.data,
        }
        if use_cache:
            cache.set(_CACHE_KEY_LIST, payload, _CACHE_TIMEOUT)
        return Response(payload)

    @swagger_auto_schema(
        operation_summary="Get Project Quality Status by ID",
        responses={200: openapi.Response("OK", _PQS_RESPONSE_SCHEMA), 404: "Not found"},
        tags=["Project Quality Status"],
    )
    def retrieve(self, request, *args, **kwargs):
        try:
            instance = ProjectQualityStatus.objects.get(pk=kwargs["pk"])
        except ProjectQualityStatus.DoesNotExist:
            return self._error(
                "Project quality status record not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        enforce_project_access_by_name(request.user, instance.projectName)

        return self._success(
            "Project quality status record retrieved successfully",
            ProjectQualityStatusSerializer(instance).data,
        )

    @swagger_auto_schema(
        operation_summary="Update Project Quality Status Record",
        request_body=_PQS_POST_SCHEMA,
        responses={200: openapi.Response("OK", _PQS_RESPONSE_SCHEMA), 400: "Validation error", 404: "Not found"},
        tags=["Project Quality Status"],
    )
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        try:
            instance = ProjectQualityStatus.objects.get(pk=kwargs["pk"])
        except ProjectQualityStatus.DoesNotExist:
            return self._error(
                "Project quality status record not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        enforce_instance_write(request.user, instance, RBACDomain.QAQC)

        payload = {
            k: v
            for k, v in _normalize_payload(request.data).items()
            if k not in _READ_ONLY
        }
        serializer = ProjectQualityStatusSerializer(instance, data=payload, partial=partial)

        if not serializer.is_valid():
            return self._error("Validation failed", errors=serializer.errors)

        try:
            updated = serializer.save()
        except DjangoValidationError as exc:
            return self._error("Validation failed", errors=exc.message_dict)
        except Exception as exc:
            logger.error(f"ProjectQualityStatus update error: {exc}")
            return self._error(
                "Failed to update quality status record",
                errors=str(exc),
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        self._invalidate_cache()
        return self._success(
            "Project quality status updated successfully",
            ProjectQualityStatusSerializer(updated).data,
        )

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Delete Project Quality Status Record",
        responses={200: openapi.Response("OK"), 404: "Not found"},
        tags=["Project Quality Status"],
    )
    def destroy(self, request, *args, **kwargs):
        try:
            instance = ProjectQualityStatus.objects.get(pk=kwargs["pk"])
        except ProjectQualityStatus.DoesNotExist:
            return self._error(
                "Project quality status record not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        enforce_instance_write(request.user, instance, RBACDomain.QAQC)

        label = f"{instance.projectName} ({instance.month:02d}/{instance.year})"
        instance.delete()
        self._invalidate_cache()
        return self._success(
            f"Project quality status record for '{label}' deleted successfully",
            {},
        )

    # -------------------------------------------------------------------------
    # LEGACY / DASHBOARD  GET .../project/{projectName}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Dashboard — latest month quality metrics",
        responses={200: openapi.Response("OK"), 404: "Not found"},
        tags=["Project Quality Status"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"project/(?P<projectName>[^/.]+)",
        url_name="by-project-name",
    )
    def get_by_project_name(self, request, projectName: str = None):
        """Return compact dashboard metrics for the most recent monthly record."""
        if not projectName or not projectName.strip():
            return self._error("projectName is required.")

        enforce_project_access_by_name(request.user, projectName.strip())

        instance = (
            ProjectQualityStatus.objects.filter(projectName__iexact=projectName.strip())
            .order_by("-year", "-month", "-updated_at")
            .first()
        )

        if instance is None:
            return self._error(
                f"No quality status record found for project '{projectName}'",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        return self._success(
            "Project quality dashboard retrieved successfully",
            dashboard_response(instance),
        )

    # -------------------------------------------------------------------------
    # MONTHLY  GET .../project/{projectName}/month/{month}/year/{year}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get quality metrics for a specific month",
        responses={200: openapi.Response("OK"), 404: "Not found"},
        tags=["Project Quality Status"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"project/(?P<projectName>[^/.]+)/month/(?P<month>\d+)/year/(?P<year>\d+)",
        url_name="by-month-year",
    )
    def get_by_month_year(self, request, projectName=None, month=None, year=None):
        try:
            month_int = int(month)
            year_int = int(year)
        except (TypeError, ValueError):
            return self._error("month and year must be valid integers.")

        if not (1 <= month_int <= 12):
            return self._error("month must be between 1 and 12.")
        if not (2000 <= year_int <= 2100):
            return self._error("year must be between 2000 and 2100.")

        project_name = projectName.strip()
        enforce_project_access_by_name(request.user, project_name)

        instance = self._find_monthly_record(project_name, month_int, year_int)

        if instance is None:
            return self._error(
                f"No quality status record found for '{project_name}' "
                f"in {month_int:02d}/{year_int}.",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        return self._success(
            f"Quality status for '{project_name}' ({month_int:02d}/{year_int}) retrieved successfully",
            monthly_response(instance),
        )

    # -------------------------------------------------------------------------
    # YEARLY SUMMARY  GET .../project/{projectName}/year/{year}/summary/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Yearly quality summary (SUM aggregation)",
        responses={200: openapi.Response("OK"), 404: "Not found"},
        tags=["Project Quality Status"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"project/(?P<projectName>[^/.]+)/year/(?P<year>\d+)/summary",
        url_name="yearly-summary",
    )
    def yearly_summary(self, request, projectName=None, year=None):
        try:
            year_int = int(year)
        except (TypeError, ValueError):
            return self._error("year must be a valid integer.")

        if not (2000 <= year_int <= 2100):
            return self._error("year must be between 2000 and 2100.")

        project_name = projectName.strip()
        enforce_project_access_by_name(request.user, project_name)

        qs = ProjectQualityStatus.objects.filter(
            projectName__iexact=project_name,
            year=year_int,
        )

        if not qs.exists():
            return self._error(
                f"No quality status records found for '{project_name}' in {year_int}.",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        metrics = _aggregate_yearly(qs)
        return self._success(
            f"Yearly quality summary for '{project_name}' ({year_int}) retrieved successfully",
            {
                "project_name": project_name,
                "year": year_int,
                **metrics,
            },
        )
