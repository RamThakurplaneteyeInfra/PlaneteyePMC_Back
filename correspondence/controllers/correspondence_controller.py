"""
Correspondence Document ViewSet.

  POST   /api/correspondence-documents/
  GET    /api/correspondence-documents/
  GET    /api/correspondence-documents/{id}/
  PATCH  /api/correspondence-documents/{id}/
  DELETE /api/correspondence-documents/{id}/
  GET    /api/correspondence-documents/dashboard/?project_name=&month=&year=
"""

import logging

from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from ..models.correspondence import CorrespondenceDocument
from .correspondence_metrics import (
    filter_by_period,
    monthly_dashboard_response,
    metrics_from_queryset,
)
from .correspondence_serializer import CorrespondenceDocumentSerializer

logger = logging.getLogger(__name__)

_CACHE_KEY_LIST = "correspondence_documents_list"
_CACHE_TIMEOUT = 300

_FIELD_ALIASES = {
    "projectName": "project_name",
    "party_type": "correspondence_type",
    "partyType": "correspondence_type",
    "delivery_date": "delivered_date",
}

_STRIP_FIELDS = {
    "deadline_date",
    "delivered_status",
    "delivery_status",
    "sr_no",
    "received",
    "delivered",
    "pending",
    "delivery_efficiency",
    "correspondence_received",
    "correspondence_delivered",
    "correspondenceReceived",
    "correspondenceDelivered",
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
        if key in _STRIP_FIELDS:
            continue
        canonical = _FIELD_ALIASES.get(key, key)
        if canonical in _STRIP_FIELDS:
            continue
        normalised[canonical] = value

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


def _parse_int_param(value, name: str):
    if value is None or value == "":
        return None, f"{name} is required."
    try:
        return int(value), None
    except (TypeError, ValueError):
        return None, f"{name} must be a valid integer."


class CorrespondencePagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


_DOC_POST_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    required=[
        "project_name",
        "month",
        "year",
        "correspondence_type",
        "description",
        "received_date",
    ],
    properties={
        "project_name": openapi.Schema(
            type=openapi.TYPE_STRING, example="Thane Project"
        ),
        "month": openapi.Schema(type=openapi.TYPE_INTEGER, example=6),
        "year": openapi.Schema(type=openapi.TYPE_INTEGER, example=2026),
        "correspondence_type": openapi.Schema(
            type=openapi.TYPE_STRING, enum=["CLIENT", "CONTRACTOR"], example="CLIENT"
        ),
        "description": openapi.Schema(
            type=openapi.TYPE_STRING, example="Site inspection report"
        ),
        "received_date": openapi.Schema(
            type=openapi.TYPE_STRING, format="date", example="2026-06-01"
        ),
        "delivered_date": openapi.Schema(
            type=openapi.TYPE_STRING,
            format="date",
            description="Optional while pending",
            example="2026-06-05",
        ),
    },
)


class CorrespondenceDocumentViewSet(viewsets.ModelViewSet):
    """Monthly project-wise correspondence document CRUD + dashboard."""

    queryset = CorrespondenceDocument.objects.all()
    serializer_class = CorrespondenceDocumentSerializer
    pagination_class = CorrespondencePagination
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = CorrespondenceDocument.objects.all()
        params = self.request.query_params

        project_name = params.get("project_name")
        if project_name:
            qs = qs.filter(project_name__icontains=project_name.strip())

        correspondence_type = params.get("correspondence_type") or params.get(
            "party_type"
        )
        if correspondence_type:
            qs = qs.filter(correspondence_type=correspondence_type.strip().upper())

        year = params.get("year")
        if year:
            year_int, err = _parse_int_param(year, "year")
            if err is None and year_int is not None:
                qs = qs.filter(year=year_int)

        month = params.get("month")
        if month:
            month_int, err = _parse_int_param(month, "month")
            if err is None and month_int is not None:
                qs = qs.filter(month=month_int)

        delivered_status = params.get("delivered_status") or params.get(
            "delivery_status"
        )
        if delivered_status:
            qs = qs.filter(delivered_status=delivered_status.strip().upper())

        return qs.order_by(
            "project_name", "year", "month", "correspondence_type", "sr_no"
        )

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

    @swagger_auto_schema(
        operation_summary="Create correspondence document",
        request_body=_DOC_POST_SCHEMA,
        tags=["Correspondence Documents"],
    )
    def create(self, request, *args, **kwargs):
        payload = _normalise_payload(request.data)
        serializer = CorrespondenceDocumentSerializer(data=payload)

        if not serializer.is_valid():
            return self._error(
                "Validation failed",
                errors=_flatten_errors(serializer.errors),
            )

        try:
            instance = serializer.save()
        except DjangoValidationError as exc:
            return self._error(
                "Validation failed", errors=_flatten_errors(exc.message_dict)
            )
        except Exception as exc:
            logger.error("Correspondence document create error: %s", exc)
            return self._error(
                "Failed to save correspondence document",
                errors=str(exc),
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        self._invalidate_list_cache()
        return self._success(
            "Correspondence document created successfully",
            CorrespondenceDocumentSerializer(instance).data,
            http_status=status.HTTP_201_CREATED,
        )

    @swagger_auto_schema(
        operation_summary="List correspondence documents",
        manual_parameters=[
            openapi.Parameter("project_name", openapi.IN_QUERY, type=openapi.TYPE_STRING),
            openapi.Parameter("month", openapi.IN_QUERY, type=openapi.TYPE_INTEGER),
            openapi.Parameter("year", openapi.IN_QUERY, type=openapi.TYPE_INTEGER),
            openapi.Parameter(
                "correspondence_type", openapi.IN_QUERY, type=openapi.TYPE_STRING
            ),
        ],
        tags=["Correspondence Documents"],
    )
    def list(self, request, *args, **kwargs):
        has_filters = any(
            request.query_params.get(k)
            for k in (
                "project_name",
                "month",
                "year",
                "correspondence_type",
                "party_type",
                "delivered_status",
                "delivery_status",
            )
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
            serializer = CorrespondenceDocumentSerializer(page, many=True)
            paginated = self.get_paginated_response(serializer.data)
            payload = {
                "success": True,
                "message": "Correspondence documents retrieved successfully",
                "data": paginated.data,
            }
            if use_cache:
                cache.set(_CACHE_KEY_LIST, payload, _CACHE_TIMEOUT)
            return Response(payload)

        serializer = CorrespondenceDocumentSerializer(queryset, many=True)
        payload = {
            "success": True,
            "message": "Correspondence documents retrieved successfully",
            "data": serializer.data,
        }
        if use_cache:
            cache.set(_CACHE_KEY_LIST, payload, _CACHE_TIMEOUT)
        return Response(payload)

    @swagger_auto_schema(tags=["Correspondence Documents"])
    def retrieve(self, request, *args, **kwargs):
        try:
            instance = CorrespondenceDocument.objects.get(pk=kwargs["pk"])
        except CorrespondenceDocument.DoesNotExist:
            return self._error(
                "Correspondence document not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )
        return self._success(
            "Correspondence document retrieved successfully",
            CorrespondenceDocumentSerializer(instance).data,
        )

    @swagger_auto_schema(
        request_body=_DOC_POST_SCHEMA,
        tags=["Correspondence Documents"],
    )
    def partial_update(self, request, *args, **kwargs):
        try:
            instance = CorrespondenceDocument.objects.get(pk=kwargs["pk"])
        except CorrespondenceDocument.DoesNotExist:
            return self._error(
                "Correspondence document not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        payload = _normalise_payload(request.data)
        serializer = CorrespondenceDocumentSerializer(
            instance, data=payload, partial=True
        )

        if not serializer.is_valid():
            return self._error(
                "Validation failed",
                errors=_flatten_errors(serializer.errors),
            )

        try:
            updated = serializer.save()
        except DjangoValidationError as exc:
            return self._error(
                "Validation failed", errors=_flatten_errors(exc.message_dict)
            )
        except Exception as exc:
            logger.error("Correspondence document update error: %s", exc)
            return self._error(
                "Failed to update correspondence document",
                errors=str(exc),
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        self._invalidate_list_cache()
        return self._success(
            "Correspondence document updated successfully",
            CorrespondenceDocumentSerializer(updated).data,
        )

    @swagger_auto_schema(tags=["Correspondence Documents"])
    def destroy(self, request, *args, **kwargs):
        try:
            instance = CorrespondenceDocument.objects.get(pk=kwargs["pk"])
        except CorrespondenceDocument.DoesNotExist:
            return self._error(
                "Correspondence document not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        label = (
            f"{instance.project_name} [{instance.correspondence_type}] "
            f"{instance.month:02d}/{instance.year} #{instance.sr_no}"
        )
        instance.delete()
        self._invalidate_list_cache()
        return self._success(
            f"Correspondence document '{label}' deleted successfully",
            {},
        )

    @swagger_auto_schema(
        operation_summary="Monthly dashboard (CLIENT + CONTRACTOR)",
        manual_parameters=[
            openapi.Parameter(
                "project_name",
                openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                required=True,
            ),
            openapi.Parameter(
                "month", openapi.IN_QUERY, type=openapi.TYPE_INTEGER, required=True
            ),
            openapi.Parameter(
                "year", openapi.IN_QUERY, type=openapi.TYPE_INTEGER, required=True
            ),
        ],
        tags=["Correspondence Documents"],
    )
    @action(detail=False, methods=["get"], url_path="dashboard")
    def dashboard(self, request):
        """
        Monthly dashboard for project_name + month + year.

        Returns received, delivered, pending, on_time, late_deliveries,
        status_breakdown, and delivery_efficiency per type.

        delivered = on_time + late_deliveries
        delivery_efficiency = (on_time / delivered) * 100
        """
        project_name = (request.query_params.get("project_name") or "").strip()
        if not project_name:
            return self._error("project_name query parameter is required.")

        month_int, err = _parse_int_param(request.query_params.get("month"), "month")
        if err:
            return self._error(err)
        year_int, err = _parse_int_param(request.query_params.get("year"), "year")
        if err:
            return self._error(err)

        if not (1 <= month_int <= 12):
            return self._error("month must be between 1 and 12.")
        if not (2000 <= year_int <= 2100):
            return self._error("year must be between 2000 and 2100.")

        period_qs = filter_by_period(
            CorrespondenceDocument.objects.all(),
            project_name=project_name,
            month=month_int,
            year=year_int,
        )

        if not period_qs.exists():
            return self._error(
                f"No correspondence documents for '{project_name}' "
                f"in {month_int:02d}/{year_int}.",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        client_qs = period_qs.filter(
            correspondence_type=CorrespondenceDocument.TYPE_CLIENT
        )
        contractor_qs = period_qs.filter(
            correspondence_type=CorrespondenceDocument.TYPE_CONTRACTOR
        )

        return self._success(
            f"Correspondence dashboard for '{project_name}' "
            f"({month_int:02d}/{year_int}) retrieved successfully",
            monthly_dashboard_response(
                project_name, month_int, year_int, client_qs, contractor_qs
            ),
        )


# Backward-compatible alias
CorrespondenceViewSet = CorrespondenceDocumentViewSet
