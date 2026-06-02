"""
Correspondence & Delivery Status Controller (ViewSet).

  POST   /api/correspondence/
  GET    /api/correspondence/
  GET    /api/correspondence/{id}/
  PUT    /api/correspondence/{id}/
  PATCH  /api/correspondence/{id}/
  DELETE /api/correspondence/{id}/
  GET    /api/correspondence/project/{projectName}/                    (legacy → project summary)
  GET    /api/correspondence/project/{projectName}/month/{m}/year/{y}/
  GET    /api/correspondence/project/{projectName}/summary/
  GET    /api/correspondence/project/{projectName}/year/{year}/summary/
  GET    /api/correspondence/project/{projectName}/dashboard/
"""

import logging
from datetime import date

from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Sum, Value
from django.db.models.functions import Coalesce
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from ..models.correspondence import CorrespondenceStatus
from .correspondence_metrics import (
    metrics_from_counts,
    metrics_from_record,
    monthly_full_response,
    dual_type_summary,
)
from .correspondence_serializer import CorrespondenceSerializer

logger = logging.getLogger(__name__)

_CACHE_KEY_LIST = "correspondence_list"
_CACHE_TIMEOUT = 300

_FIELD_ALIASES = {
    "project_name": "_project_name",
    "projectName": "_project_name",
    "correspondenceReceived": "correspondence_received",
    "correspondenceDelivered": "correspondence_delivered",
}

_STRIP_FIELDS = {
    "pending_correspondence",
    "delivery_efficiency",
    "pendingCorrespondence",
    "deliveryPercentage",
    "id",
    "created_at",
    "updated_at",
}


def _normalise_payload(data: dict) -> dict:
    if hasattr(data, "copy"):
        data = data.copy()
    else:
        data = dict(data)

    normalised = {}
    for key, value in data.items():
        canonical = _FIELD_ALIASES.get(key, key)
        if canonical in _STRIP_FIELDS or key in _STRIP_FIELDS:
            continue
        normalised[canonical] = value

    for field in (
        "correspondence_received",
        "correspondence_delivered",
        "month",
        "year",
    ):
        if field in normalised:
            try:
                normalised[field] = int(normalised[field])
            except (TypeError, ValueError):
                pass

    if "correspondence_type" in normalised and isinstance(
        normalised["correspondence_type"], str
    ):
        normalised["correspondence_type"] = normalised["correspondence_type"].upper()

    return normalised


def _flatten_errors(errors) -> dict:
    flat: dict = {}
    if isinstance(errors, dict):
        for field, messages in errors.items():
            if isinstance(messages, list):
                flat[field] = " ".join(str(m) for m in messages)
            elif isinstance(messages, dict):
                flat[field] = _flatten_errors(messages)
            else:
                flat[field] = str(messages)
    elif isinstance(errors, list):
        return {"detail": " ".join(str(m) for m in errors)}
    else:
        return {"detail": str(errors)}
    return flat


def _aggregate_queryset(queryset) -> dict:
    agg = queryset.aggregate(
        received=Coalesce(Sum("correspondence_received"), Value(0)),
        delivered=Coalesce(Sum("correspondence_delivered"), Value(0)),
    )
    return metrics_from_counts(agg["received"], agg["delivered"])


def _records_by_type(queryset):
    by_type = {r.correspondence_type: r for r in queryset}
    return (
        by_type.get(CorrespondenceStatus.TYPE_CLIENT),
        by_type.get(CorrespondenceStatus.TYPE_CONTRACTOR),
    )


class CorrespondencePagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


_CORRESPONDENCE_POST_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    required=["project_name", "month", "year", "correspondence_type"],
    properties={
        "project_name": openapi.Schema(type=openapi.TYPE_STRING, example="Thane Project"),
        "month": openapi.Schema(type=openapi.TYPE_INTEGER, example=6),
        "year": openapi.Schema(type=openapi.TYPE_INTEGER, example=2026),
        "correspondence_type": openapi.Schema(
            type=openapi.TYPE_STRING, enum=["CLIENT", "CONTRACTOR"], example="CLIENT"
        ),
        "correspondence_received": openapi.Schema(type=openapi.TYPE_INTEGER, example=120),
        "correspondence_delivered": openapi.Schema(type=openapi.TYPE_INTEGER, example=110),
    },
)

_CORRESPONDENCE_RESPONSE_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    properties={
        "success": openapi.Schema(type=openapi.TYPE_BOOLEAN, example=True),
        "message": openapi.Schema(type=openapi.TYPE_STRING),
        "data": openapi.Schema(type=openapi.TYPE_OBJECT),
    },
)


class CorrespondenceViewSet(viewsets.ModelViewSet):
    """
    Monthly Correspondence & Delivery Status ViewSet.

    One record per (project, month, year, correspondence_type).
    pending_correspondence and delivery_efficiency are computed on read.
    """

    queryset = CorrespondenceStatus.objects.select_related("project").all()
    serializer_class = CorrespondenceSerializer
    permission_classes = [AllowAny]
    pagination_class = CorrespondencePagination

    def get_queryset(self):
        qs = CorrespondenceStatus.objects.select_related("project").all()

        project_name = self.request.query_params.get("project_name")
        if project_name:
            qs = qs.filter(project__name__icontains=project_name.strip())

        correspondence_type = self.request.query_params.get("correspondence_type")
        if correspondence_type:
            qs = qs.filter(correspondence_type=correspondence_type.strip().upper())

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

        return qs.order_by("project__name", "year", "month", "correspondence_type")

    def _invalidate_list_cache(self):
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

    def _find_monthly_record(self, project_name: str, month: int, year: int, corr_type: str):
        return (
            CorrespondenceStatus.objects.select_related("project")
            .filter(
                project__name__iexact=project_name.strip(),
                month=month,
                year=year,
                correspondence_type=corr_type,
            )
            .first()
        )

    def _project_queryset(self, project_name: str):
        return CorrespondenceStatus.objects.filter(
            project__name__iexact=project_name.strip()
        )

    def _upsert_from_payload(self, payload: dict):
        project_name = payload.get("_project_name", "").strip()
        month = payload.get("month")
        year = payload.get("year")
        corr_type = payload.get("correspondence_type")

        existing = None
        if project_name and month is not None and year is not None and corr_type:
            existing = self._find_monthly_record(
                project_name, int(month), int(year), corr_type
            )

        if existing is not None:
            serializer = CorrespondenceSerializer(existing, data=payload)
        else:
            serializer = CorrespondenceSerializer(data=payload)

        return serializer, existing

    @swagger_auto_schema(
        operation_summary="Create Correspondence Record",
        request_body=_CORRESPONDENCE_POST_SCHEMA,
        responses={201: openapi.Response("Created", _CORRESPONDENCE_RESPONSE_SCHEMA), 400: "Validation error"},
        tags=["Correspondence"],
    )
    def create(self, request, *args, **kwargs):
        """Create or update monthly record (upsert by project + month + year + type)."""
        payload = _normalise_payload(request.data)

        serializer, existing = self._upsert_from_payload(payload)

        if not serializer.is_valid():
            return self._error(
                "Validation failed",
                errors=_flatten_errors(serializer.errors),
            )

        try:
            instance = serializer.save()
        except DjangoValidationError as exc:
            return self._error("Validation failed", errors=_flatten_errors(exc.message_dict))
        except Exception as exc:
            logger.error(f"Correspondence create error: {exc}")
            return self._error(
                "Failed to save correspondence record",
                errors=str(exc),
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        self._invalidate_list_cache()

        http_status = status.HTTP_200_OK if existing else status.HTTP_201_CREATED
        message = (
            "Correspondence record updated successfully"
            if existing
            else "Correspondence record saved successfully"
        )

        return self._success(
            message,
            CorrespondenceSerializer(instance).data,
            http_status=http_status,
        )

    @swagger_auto_schema(
        operation_summary="List Correspondence Records",
        manual_parameters=[
            openapi.Parameter("project_name", openapi.IN_QUERY, type=openapi.TYPE_STRING, required=False),
            openapi.Parameter("month", openapi.IN_QUERY, type=openapi.TYPE_INTEGER, required=False),
            openapi.Parameter("year", openapi.IN_QUERY, type=openapi.TYPE_INTEGER, required=False),
            openapi.Parameter(
                "correspondence_type",
                openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                enum=["CLIENT", "CONTRACTOR"],
                required=False,
            ),
        ],
        responses={200: openapi.Response("OK", _CORRESPONDENCE_RESPONSE_SCHEMA)},
        tags=["Correspondence"],
    )
    def list(self, request, *args, **kwargs):
        has_filters = any(
            request.query_params.get(k)
            for k in ("project_name", "month", "year", "correspondence_type")
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
            serializer = CorrespondenceSerializer(page, many=True)
            paginated = self.get_paginated_response(serializer.data)
            payload = {
                "success": True,
                "message": "Correspondence records retrieved successfully",
                "data": paginated.data,
            }
            if use_cache:
                cache.set(_CACHE_KEY_LIST, payload, _CACHE_TIMEOUT)
            return Response(payload)

        serializer = CorrespondenceSerializer(queryset, many=True)
        payload = {
            "success": True,
            "message": "Correspondence records retrieved successfully",
            "data": serializer.data,
        }
        if use_cache:
            cache.set(_CACHE_KEY_LIST, payload, _CACHE_TIMEOUT)
        return Response(payload)

    @swagger_auto_schema(
        operation_summary="Get Correspondence by ID",
        responses={200: openapi.Response("OK", _CORRESPONDENCE_RESPONSE_SCHEMA), 404: "Not found"},
        tags=["Correspondence"],
    )
    def retrieve(self, request, *args, **kwargs):
        try:
            instance = CorrespondenceStatus.objects.select_related("project").get(pk=kwargs["pk"])
        except CorrespondenceStatus.DoesNotExist:
            return self._error(
                "Correspondence record not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )
        return self._success(
            "Correspondence record retrieved successfully",
            CorrespondenceSerializer(instance).data,
        )

    @swagger_auto_schema(
        operation_summary="Update Correspondence Record",
        request_body=_CORRESPONDENCE_POST_SCHEMA,
        responses={200: openapi.Response("OK", _CORRESPONDENCE_RESPONSE_SCHEMA), 400: "Validation error", 404: "Not found"},
        tags=["Correspondence"],
    )
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        try:
            instance = CorrespondenceStatus.objects.select_related("project").get(pk=kwargs["pk"])
        except CorrespondenceStatus.DoesNotExist:
            return self._error(
                "Correspondence record not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        payload = _normalise_payload(request.data)
        serializer = CorrespondenceSerializer(instance, data=payload, partial=partial)

        if not serializer.is_valid():
            return self._error(
                "Validation failed",
                errors=_flatten_errors(serializer.errors),
            )

        try:
            updated = serializer.save()
        except DjangoValidationError as exc:
            return self._error("Validation failed", errors=_flatten_errors(exc.message_dict))
        except Exception as exc:
            logger.error(f"Correspondence update error: {exc}")
            return self._error(
                "Failed to update correspondence record",
                errors=str(exc),
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        self._invalidate_list_cache()
        return self._success(
            "Correspondence record updated successfully",
            CorrespondenceSerializer(updated).data,
        )

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Delete Correspondence Record",
        responses={200: openapi.Response("OK"), 404: "Not found"},
        tags=["Correspondence"],
    )
    def destroy(self, request, *args, **kwargs):
        try:
            instance = CorrespondenceStatus.objects.select_related("project").get(pk=kwargs["pk"])
        except CorrespondenceStatus.DoesNotExist:
            return self._error(
                "Correspondence record not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        label = (
            f"{instance.project_name} [{instance.correspondence_type}] "
            f"({instance.month:02d}/{instance.year})"
        )
        instance.delete()
        self._invalidate_list_cache()
        return self._success(
            f"Correspondence record for '{label}' deleted successfully",
            {},
        )

    # -------------------------------------------------------------------------
    # MONTHLY  GET .../project/{projectName}/month/{month}/year/{year}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Monthly CLIENT + CONTRACTOR correspondence",
        responses={200: openapi.Response("OK"), 404: "Not found"},
        tags=["Correspondence"],
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
        records = self._project_queryset(project_name).filter(
            month=month_int, year=year_int
        )

        if not records.exists():
            return self._error(
                f"No correspondence records found for '{project_name}' "
                f"in {month_int:02d}/{year_int}.",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        client, contractor = _records_by_type(records)
        return self._success(
            f"Correspondence for '{project_name}' ({month_int:02d}/{year_int}) retrieved successfully",
            monthly_full_response(project_name, month_int, year_int, client, contractor),
        )

    # -------------------------------------------------------------------------
    # PROJECT SUMMARY  GET .../project/{projectName}/summary/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Project-wide correspondence summary (all months, SUM)",
        responses={200: openapi.Response("OK"), 404: "Not found"},
        tags=["Correspondence"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"project/(?P<projectName>[^/.]+)/summary",
        url_name="project-summary",
    )
    def project_summary(self, request, projectName=None):
        if not projectName or not projectName.strip():
            return self._error("projectName is required.")

        project_name = projectName.strip()
        qs = self._project_queryset(project_name)

        if not qs.exists():
            return self._error(
                f"No correspondence records found for project '{project_name}'",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        client_qs = qs.filter(correspondence_type=CorrespondenceStatus.TYPE_CLIENT)
        contractor_qs = qs.filter(correspondence_type=CorrespondenceStatus.TYPE_CONTRACTOR)

        return self._success(
            f"Project correspondence summary for '{project_name}' retrieved successfully",
            dual_type_summary(
                project_name,
                _aggregate_queryset(client_qs),
                _aggregate_queryset(contractor_qs),
            ),
        )

    # -------------------------------------------------------------------------
    # YEARLY SUMMARY  GET .../project/{projectName}/year/{year}/summary/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Yearly correspondence summary (SUM for selected year)",
        responses={200: openapi.Response("OK"), 404: "Not found"},
        tags=["Correspondence"],
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
        qs = self._project_queryset(project_name).filter(year=year_int)

        if not qs.exists():
            return self._error(
                f"No correspondence records found for '{project_name}' in {year_int}.",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        client_qs = qs.filter(correspondence_type=CorrespondenceStatus.TYPE_CLIENT)
        contractor_qs = qs.filter(correspondence_type=CorrespondenceStatus.TYPE_CONTRACTOR)

        return self._success(
            f"Yearly correspondence summary for '{project_name}' ({year_int}) retrieved successfully",
            dual_type_summary(
                project_name,
                _aggregate_queryset(client_qs),
                _aggregate_queryset(contractor_qs),
                year=year_int,
            ),
        )

    # -------------------------------------------------------------------------
    # DASHBOARD  GET .../project/{projectName}/dashboard/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Dashboard — current month + project totals",
        responses={200: openapi.Response("OK"), 404: "Not found"},
        tags=["Correspondence"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"project/(?P<projectName>[^/.]+)/dashboard",
        url_name="dashboard",
    )
    def dashboard(self, request, projectName=None):
        if not projectName or not projectName.strip():
            return self._error("projectName is required.")

        project_name = projectName.strip()
        qs = self._project_queryset(project_name)

        if not qs.exists():
            return self._error(
                f"No correspondence records found for project '{project_name}'",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        today = date.today()
        current_records = qs.filter(month=today.month, year=today.year)
        client_cm, contractor_cm = _records_by_type(current_records)

        client_all = qs.filter(correspondence_type=CorrespondenceStatus.TYPE_CLIENT)
        contractor_all = qs.filter(correspondence_type=CorrespondenceStatus.TYPE_CONTRACTOR)

        return self._success(
            f"Correspondence dashboard for '{project_name}' retrieved successfully",
            {
                "project_name": project_name,
                "current_month": {
                    "client": metrics_from_record(client_cm),
                    "contractor": metrics_from_record(contractor_cm),
                },
                "project_summary": {
                    "client": _aggregate_queryset(client_all),
                    "contractor": _aggregate_queryset(contractor_all),
                },
            },
        )

    # -------------------------------------------------------------------------
    # LEGACY  GET .../project/{projectName}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get correspondence by project name (legacy)",
        operation_description="Returns aggregated project summary (same as /summary/).",
        responses={200: openapi.Response("OK", _CORRESPONDENCE_RESPONSE_SCHEMA), 404: "Not found"},
        tags=["Correspondence"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"project/(?P<projectName>[^/.]+)",
        url_name="by-project-name",
    )
    def get_by_project_name(self, request, projectName: str = None):
        return self.project_summary(request, projectName=projectName)
