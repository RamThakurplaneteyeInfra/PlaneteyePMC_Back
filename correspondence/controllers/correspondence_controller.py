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
    VIEW_CUMULATIVE,
    VIEW_MONTHLY,
    dashboard_response,
    filter_by_period,
    get_scl_delivered_summary,
    normalize_view,
)
from .correspondence_serializer import CorrespondenceDocumentSerializer
from .inbound_serializer import InboundCorrespondenceSerializer
from .scl_delivered_serializer import SCLDeliveredCorrespondenceSerializer
from ..models.inbound_summary import InboundCorrespondenceSummary
from ..models.scl_delivered_summary import SCLDeliveredCorrespondenceSummary

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
    "record",
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

_SCL_DELIVERED_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    required=["project_name", "month", "year"],
    properties={
        "project_name": openapi.Schema(type=openapi.TYPE_STRING, example="Thane Project"),
        "month": openapi.Schema(type=openapi.TYPE_INTEGER, example=6),
        "year": openapi.Schema(type=openapi.TYPE_INTEGER, example=2026),
        "view": openapi.Schema(
            type=openapi.TYPE_STRING,
            enum=[VIEW_MONTHLY, VIEW_CUMULATIVE],
            example=VIEW_MONTHLY,
        ),
        "client_received": openapi.Schema(type=openapi.TYPE_INTEGER, example=25),
        "client_delivered": openapi.Schema(type=openapi.TYPE_INTEGER, example=18),
        "client_record": openapi.Schema(type=openapi.TYPE_INTEGER, example=2),
        "contractor_received": openapi.Schema(type=openapi.TYPE_INTEGER, example=40),
        "contractor_delivered": openapi.Schema(type=openapi.TYPE_INTEGER, example=30),
        "contractor_record": openapi.Schema(type=openapi.TYPE_INTEGER, example=3),
        "other_agency_received": openapi.Schema(type=openapi.TYPE_INTEGER, example=15),
        "other_agency_delivered": openapi.Schema(type=openapi.TYPE_INTEGER, example=10),
        "other_agency_record": openapi.Schema(type=openapi.TYPE_INTEGER, example=1),
    },
)

_INBOUND_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    required=["project_name", "month", "year"],
    properties={
        "project_name": openapi.Schema(type=openapi.TYPE_STRING, example="Thane Project"),
        "month": openapi.Schema(type=openapi.TYPE_INTEGER, example=6),
        "year": openapi.Schema(type=openapi.TYPE_INTEGER, example=2026),
        "view": openapi.Schema(
            type=openapi.TYPE_STRING,
            enum=[VIEW_MONTHLY, VIEW_CUMULATIVE],
            example=VIEW_MONTHLY,
        ),
        "client_received": openapi.Schema(type=openapi.TYPE_INTEGER, example=10),
        "client_delivered": openapi.Schema(type=openapi.TYPE_INTEGER, example=6),
        "client_record": openapi.Schema(type=openapi.TYPE_INTEGER, example=2),
        "contractor_received": openapi.Schema(type=openapi.TYPE_INTEGER, example=12),
        "contractor_delivered": openapi.Schema(type=openapi.TYPE_INTEGER, example=8),
        "contractor_record": openapi.Schema(type=openapi.TYPE_INTEGER, example=1),
        "client": openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                "received": openapi.Schema(type=openapi.TYPE_INTEGER),
                "delivered": openapi.Schema(type=openapi.TYPE_INTEGER),
                "record": openapi.Schema(type=openapi.TYPE_INTEGER),
            },
        ),
        "contractor": openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                "received": openapi.Schema(type=openapi.TYPE_INTEGER),
                "delivered": openapi.Schema(type=openapi.TYPE_INTEGER),
                "record": openapi.Schema(type=openapi.TYPE_INTEGER),
            },
        ),
    },
)


class CorrespondenceDocumentViewSet(viewsets.ModelViewSet):
    """Monthly project-wise correspondence document CRUD + dashboard."""

    queryset = CorrespondenceDocument.objects.all()
    serializer_class = CorrespondenceDocumentSerializer
    pagination_class = CorrespondencePagination
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]

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
        operation_summary="Correspondence dashboard (monthly or cumulative)",
        methods=["get"],
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
            openapi.Parameter(
                "view",
                openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                enum=[VIEW_MONTHLY, VIEW_CUMULATIVE],
            ),
        ],
        tags=["Correspondence Documents"],
    )
    @swagger_auto_schema(
        operation_summary="Save SCL delivered counts via dashboard",
        methods=["post", "put", "patch"],
        request_body=_SCL_DELIVERED_SCHEMA,
        tags=["Correspondence Documents"],
    )
    @action(detail=False, methods=["get", "post", "put", "patch"], url_path="dashboard")
    def dashboard(self, request):
        """
        Dashboard for project_name + month + year.

        GET: statistics (view=monthly|cumulative).
        POST/PUT/PATCH: save SCL delivered correspondence counts (same body as
        /scl-delivered-correspondence/).
        """
        if request.method != "GET":
            allow_create = request.method == "POST"
            return self._save_scl_delivered(request, allow_create=allow_create)

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

        view = normalize_view(request.query_params.get("view"))

        period_qs = filter_by_period(
            CorrespondenceDocument.objects.all(),
            project_name=project_name,
            month=month_int,
            year=year_int,
            view=view,
        )

        if not period_qs.exists():
            view_label = "year-to-date" if view == VIEW_CUMULATIVE else "month"
            return self._error(
                f"No correspondence documents for '{project_name}' "
                f"in the selected {view_label} ({month_int:02d}/{year_int}).",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        data = dashboard_response(
            project_name,
            month_int,
            year_int,
            period_qs,
            view=view,
        )

        view_label = "cumulative" if view == VIEW_CUMULATIVE else "monthly"
        return self._success(
            f"Correspondence {view_label} dashboard for '{project_name}' "
            f"({month_int:02d}/{year_int}) retrieved successfully",
            data,
        )

    def _parse_scl_request(self, request, *, from_query: bool = False):
        """Parse SCL delivered params from query string or JSON body."""
        source = request.query_params if from_query else request.data
        project_name = (source.get("project_name") or source.get("projectName") or "").strip()
        if not project_name:
            return None, self._error("project_name is required.")

        month_int, err = _parse_int_param(source.get("month"), "month")
        if err:
            return None, self._error(err)
        year_int, err = _parse_int_param(source.get("year"), "year")
        if err:
            return None, self._error(err)

        if not (1 <= month_int <= 12):
            return None, self._error("month must be between 1 and 12.")
        if not (2000 <= year_int <= 2100):
            return None, self._error("year must be between 2000 and 2100.")

        view = normalize_view(source.get("view", VIEW_MONTHLY))
        return {
            "project_name": project_name,
            "month": month_int,
            "year": year_int,
            "view": view,
            "raw": source,
        }, None

    def _period_documents(self, project_name: str, month: int, year: int, view: str):
        return filter_by_period(
            CorrespondenceDocument.objects.all(),
            project_name=project_name,
            month=month,
            year=year,
            view=view,
        )

    def _save_scl_delivered(self, request, *, allow_create: bool = True):
        data = request.data
        project_name = (data.get("project_name") or data.get("projectName") or "").strip()
        if not project_name:
            return self._error("project_name is required.")

        serializer = SCLDeliveredCorrespondenceSerializer(data=data)
        if not serializer.is_valid():
            return self._error(
                "Validation failed",
                errors=_flatten_errors(serializer.errors),
            )

        validated = serializer.validated_data
        existing = SCLDeliveredCorrespondenceSummary.objects.filter(
            project_name__iexact=validated["project_name"],
            month=validated["month"],
            year=validated["year"],
            view=validated["view"],
        ).first()

        if not allow_create and existing is None:
            return self._error(
                "SCL delivered correspondence record not found. Use POST to create.",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        defaults = {
            "project_name": validated["project_name"],
            "client_received": validated["client_received"],
            "client_delivered": validated["client_delivered"],
            "client_record": 0,
            "contractor_received": validated["contractor_received"],
            "contractor_delivered": validated["contractor_delivered"],
            "contractor_record": 0,
            "other_agency_received": validated["other_agency_received"],
            "other_agency_delivered": validated["other_agency_delivered"],
            "other_agency_record": 0,
            # Keep legacy delivered-only columns in sync for old admin/data uses.
            "client": validated["client_delivered"],
            "contractor": validated["contractor_delivered"],
            "other_agency": validated["other_agency_delivered"],
        }

        if existing:
            for key, value in defaults.items():
                setattr(existing, key, value)
            existing.save()
            instance = existing
            created = False
        else:
            instance = SCLDeliveredCorrespondenceSummary.objects.create(
                month=validated["month"],
                year=validated["year"],
                view=validated["view"],
                **defaults,
            )
            created = True

        self._invalidate_list_cache()
        period_qs = self._period_documents(
            instance.project_name,
            instance.month,
            instance.year,
            instance.view,
        )
        payload = SCLDeliveredCorrespondenceSerializer(
            instance,
            context={"document_qs": period_qs},
        ).data
        message = (
            "SCL delivered correspondence created successfully"
            if created
            else "SCL delivered correspondence updated successfully"
        )
        return self._success(
            message,
            payload,
            http_status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def _handle_scl_delivered_correspondence(self, request):
        """
        SCL Delivered Correspondence — save/load counts by recipient.

        POST  → create or upsert counts
        PUT   → update existing (404 if missing)
        PATCH → partial update existing (404 if missing)
        GET   → retrieve stored counts
        """
        if request.method == "GET":
            parsed, error = self._parse_scl_request(request, from_query=True)
            if error:
                return error

            summary = get_scl_delivered_summary(
                parsed["project_name"],
                parsed["month"],
                parsed["year"],
                parsed["view"],
            )
            if summary is None:
                return self._success(
                    "No SCL delivered correspondence record found",
                    {
                        "project_name": parsed["project_name"],
                        "month": parsed["month"],
                        "year": parsed["year"],
                        "view": parsed["view"],
                        "scl_delivered_correspondence": {
                            "client": {
                                "received": 0,
                                "delivered": 0,
                                "record": 0,
                                "pending": 0,
                            },
                            "contractor": {
                                "received": 0,
                                "delivered": 0,
                                "record": 0,
                                "pending": 0,
                            },
                            "other_agency": {
                                "received": 0,
                                "delivered": 0,
                                "record": 0,
                                "pending": 0,
                            },
                            "totals": {
                                "received": 0,
                                "delivered": 0,
                                "record": 0,
                                "pending": 0,
                            },
                            "client_delivered": 0,
                            "contractor_delivered": 0,
                            "other_agency_delivered": 0,
                            "total": 0,
                        },
                    },
                )
            return self._success(
                "SCL delivered correspondence retrieved successfully",
                SCLDeliveredCorrespondenceSerializer(
                    summary,
                    context={
                        "document_qs": self._period_documents(
                            parsed["project_name"],
                            parsed["month"],
                            parsed["year"],
                            parsed["view"],
                        )
                    },
                ).data,
            )

        allow_create = request.method == "POST"
        return self._save_scl_delivered(request, allow_create=allow_create)

    def _save_inbound_correspondence(self, request, *, allow_create: bool = True):
        data = request.data
        project_name = (data.get("project_name") or data.get("projectName") or "").strip()
        if not project_name:
            return self._error("project_name is required.")

        serializer = InboundCorrespondenceSerializer(data=data)
        if not serializer.is_valid():
            return self._error(
                "Validation failed",
                errors=_flatten_errors(serializer.errors),
            )

        validated = serializer.validated_data
        existing = InboundCorrespondenceSummary.objects.filter(
            project_name__iexact=validated["project_name"],
            month=validated["month"],
            year=validated["year"],
            view=validated["view"],
        ).first()

        if not allow_create and existing is None:
            return self._error(
                "Inbound correspondence record not found. Use POST to create.",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        defaults = {
            "project_name": validated["project_name"],
            "client_received": validated["client_received"],
            "client_delivered": validated["client_delivered"],
            "client_record": 0,
            "contractor_received": validated["contractor_received"],
            "contractor_delivered": validated["contractor_delivered"],
            "contractor_record": 0,
        }

        if existing:
            for key, value in defaults.items():
                setattr(existing, key, value)
            existing.save()
            instance = existing
        else:
            instance = InboundCorrespondenceSummary.objects.create(
                month=validated["month"],
                year=validated["year"],
                view=validated["view"],
                **defaults,
            )

        self._invalidate_list_cache()
        period_qs = self._period_documents(
            instance.project_name,
            instance.month,
            instance.year,
            instance.view,
        )
        http_status = status.HTTP_200_OK if existing else status.HTTP_201_CREATED
        message = (
            "Inbound correspondence updated successfully"
            if existing
            else "Inbound correspondence created successfully"
        )
        return self._success(
            message,
            InboundCorrespondenceSerializer(
                instance,
                context={"document_qs": period_qs},
            ).data,
            http_status=http_status,
        )

    def _handle_inbound_correspondence(self, request):
        """Client / Contractor correspondence counts — save/load by project period."""
        if request.method == "GET":
            parsed, error = self._parse_scl_request(request, from_query=True)
            if error:
                return error

            from .correspondence_metrics import get_inbound_summary

            summary = get_inbound_summary(
                parsed["project_name"],
                parsed["month"],
                parsed["year"],
                parsed["view"],
            )
            if summary is None:
                empty = {"received": 0, "delivered": 0, "record": 0, "pending": 0}
                return self._success(
                    "No inbound correspondence record found",
                    {
                        "project_name": parsed["project_name"],
                        "month": parsed["month"],
                        "year": parsed["year"],
                        "view": parsed["view"],
                        "client": empty,
                        "contractor": empty,
                    },
                )
            return self._success(
                "Inbound correspondence retrieved successfully",
                InboundCorrespondenceSerializer(
                    summary,
                    context={
                        "document_qs": self._period_documents(
                            parsed["project_name"],
                            parsed["month"],
                            parsed["year"],
                            parsed["view"],
                        )
                    },
                ).data,
            )

        allow_create = request.method == "POST"
        return self._save_inbound_correspondence(request, allow_create=allow_create)

    @swagger_auto_schema(
        operation_summary="Get inbound (Client / Contractor) correspondence counts",
        methods=["get"],
        manual_parameters=[
            openapi.Parameter("project_name", openapi.IN_QUERY, type=openapi.TYPE_STRING, required=True),
            openapi.Parameter("month", openapi.IN_QUERY, type=openapi.TYPE_INTEGER, required=True),
            openapi.Parameter("year", openapi.IN_QUERY, type=openapi.TYPE_INTEGER, required=True),
            openapi.Parameter("view", openapi.IN_QUERY, type=openapi.TYPE_STRING, enum=[VIEW_MONTHLY, VIEW_CUMULATIVE]),
        ],
        tags=["Correspondence Documents"],
    )
    @swagger_auto_schema(
        operation_summary="Create or upsert inbound correspondence counts",
        methods=["post"],
        request_body=_INBOUND_SCHEMA,
        tags=["Correspondence Documents"],
    )
    @swagger_auto_schema(
        operation_summary="Update inbound correspondence counts",
        methods=["put", "patch"],
        request_body=_INBOUND_SCHEMA,
        tags=["Correspondence Documents"],
    )
    @action(
        detail=False,
        methods=["get", "post", "put", "patch"],
        url_path="inbound-correspondence",
    )
    def inbound_correspondence(self, request):
        return self._handle_inbound_correspondence(request)

    @swagger_auto_schema(
        operation_summary="Get SCL delivered correspondence counts",
        methods=["get"],
        manual_parameters=[
            openapi.Parameter("project_name", openapi.IN_QUERY, type=openapi.TYPE_STRING, required=True),
            openapi.Parameter("month", openapi.IN_QUERY, type=openapi.TYPE_INTEGER, required=True),
            openapi.Parameter("year", openapi.IN_QUERY, type=openapi.TYPE_INTEGER, required=True),
            openapi.Parameter("view", openapi.IN_QUERY, type=openapi.TYPE_STRING, enum=[VIEW_MONTHLY, VIEW_CUMULATIVE]),
        ],
        tags=["Correspondence Documents"],
    )
    @swagger_auto_schema(
        operation_summary="Create or upsert SCL delivered correspondence counts",
        methods=["post"],
        request_body=_SCL_DELIVERED_SCHEMA,
        tags=["Correspondence Documents"],
    )
    @swagger_auto_schema(
        operation_summary="Update SCL delivered correspondence counts",
        methods=["put", "patch"],
        request_body=_SCL_DELIVERED_SCHEMA,
        tags=["Correspondence Documents"],
    )
    @action(
        detail=False,
        methods=["get", "post", "put", "patch"],
        url_path="scl-delivered-correspondence",
    )
    def scl_delivered_correspondence(self, request):
        return self._handle_scl_delivered_correspondence(request)

    @action(
        detail=False,
        methods=["get", "post", "put", "patch"],
        url_path="scl-delivered",
    )
    def scl_delivered(self, request):
        """Frontend alias for scl-delivered-correspondence."""
        return self._handle_scl_delivered_correspondence(request)


# Backward-compatible alias
CorrespondenceViewSet = CorrespondenceDocumentViewSet
