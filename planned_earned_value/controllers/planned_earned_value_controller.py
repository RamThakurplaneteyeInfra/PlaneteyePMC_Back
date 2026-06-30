"""
Planned vs Earned Value Controller (ViewSet).

Endpoints:
  POST   /api/planned-earned-value/
  GET    /api/planned-earned-value/
  GET    /api/planned-earned-value/{id}/
  PUT    /api/planned-earned-value/{id}/
  PATCH  /api/planned-earned-value/{id}/
  DELETE /api/planned-earned-value/{id}/
  GET    /api/planned-earned-value/project/{projectName}/                     (legacy)
  GET    /api/planned-earned-value/project/{projectName}/month/{m}/year/{y}/  (dashboard)
  GET    /api/planned-earned-value/project/{projectName}/year/{y}/summary/    (yearly)
"""

import logging
from decimal import Decimal

from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Sum, Value
from django.db.models.functions import Coalesce
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from accounts.permissions import IsAuthenticatedProjectRBAC
from accounts.rbac import RBACDomain, extract_project_name_from_data
from accounts.rbac_checks import (
    apply_project_rbac_to_queryset,
    enforce_instance_write,
    enforce_project_access_by_name,
    enforce_project_write_by_name,
)

from ..models.planned_earned_value import PlannedEarnedValue
from .planned_earned_value_serializer import PlannedEarnedValueSerializer

logger = logging.getLogger(__name__)

_CACHE_KEY_LIST = "planned_earned_value_list"
_CACHE_TIMEOUT = 300

_READ_ONLY_FIELDS = {
    "variance",
    "variancePercentage",
    "performancePercentage",
    "schedulePerformanceIndex",
    "spi",
    "performanceStatus",
    "performance_percentage",
    "scl",
    "contractor",
    "SCL",
    "CONTRACTOR",
    "id",
    "created_at",
    "updated_at",
}


def _to_decimal(value) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    return Decimal(str(value))


def _extract_nested_type_values(
    data,
    existing_record=None,
) -> tuple[Decimal, Decimal]:
    """
    Read planned/earned from nested scl/contractor object.

    Missing keys on UPDATE fall back to the existing DB record — never default to 0.
    On CREATE both fields must be present in the payload.
    """
    if not isinstance(data, dict):
        raise DjangoValidationError({"detail": "Nested section must be an object."})

    planned = None
    earned = None

    if "planned_value" in data:
        planned = _to_decimal(data["planned_value"])
    elif "plannedValue" in data:
        planned = _to_decimal(data["plannedValue"])

    if "earned_value" in data:
        earned = _to_decimal(data["earned_value"])
    elif "earnedValue" in data:
        earned = _to_decimal(data["earnedValue"])

    if existing_record is not None:
        if planned is None:
            planned = existing_record.plannedValue
        if earned is None:
            earned = existing_record.earnedValue
        return planned, earned

    errors = {}
    if planned is None:
        errors["planned_value"] = "planned_value is required when creating a new record."
    if earned is None:
        errors["earned_value"] = "earned_value is required when creating a new record."
    if errors:
        raise DjangoValidationError(errors)

    return planned, earned


def _nested_section_data(data, *keys):
    """Return nested section only if the key is explicitly present in the payload."""
    for key in keys:
        if key in data:
            return data[key]
    return None


def _nested_section_present(data, *keys) -> bool:
    return any(key in data for key in keys)


def _is_nested_payload(data) -> bool:
    if not isinstance(data, dict):
        return False
    return any(
        key in data
        for key in ("scl", "contractor", "SCL", "CONTRACTOR")
    )


def _metrics_for_response(record) -> dict | None:
    """Dashboard-style metrics; None when no DB record exists."""
    if record is None:
        return None
    metrics = _metrics_from_record(record)
    return {
        "planned_value": float(metrics["planned_value"]),
        "earned_value": float(metrics["earned_value"]),
        "variance": float(metrics["variance"]),
        "spi": metrics["spi"],
        "performance_percentage": metrics["performance_percentage"],
    }


def _build_month_dashboard_response(project_name: str, month: int, year: int) -> dict:
    records = PlannedEarnedValue.objects.filter(
        projectName__iexact=project_name,
        month=month,
        year=year,
    )
    by_type = {r.value_type: r for r in records}
    scl = by_type.get(PlannedEarnedValue.VALUE_TYPE_SCL)
    contractor = by_type.get(PlannedEarnedValue.VALUE_TYPE_CONTRACTOR)
    return {
        "project_name": project_name,
        "month": month,
        "year": year,
        "scl": _metrics_for_response(scl),
        "contractor": _metrics_for_response(contractor),
    }


def _metrics_from_totals(planned, earned) -> dict:
    """Compute KPI metrics from planned/earned totals."""
    planned = Decimal(planned or 0)
    earned = Decimal(earned or 0)
    variance = earned - planned
    spi = round(float(earned / planned), 4) if planned > 0 else 0.0
    performance_percentage = round(float(earned / planned) * 100, 2) if planned > 0 else 0.0
    return {
        "planned_value": planned,
        "earned_value": earned,
        "variance": variance,
        "spi": spi,
        "performance_percentage": performance_percentage,
    }


def _empty_metrics() -> dict:
    return _metrics_from_totals(0, 0)


def _metrics_from_record(record) -> dict:
    if record is None:
        return _empty_metrics()
    return _metrics_from_totals(record.plannedValue, record.earnedValue)


def _aggregate_by_type(queryset, value_type: str) -> dict:
    """SUM monthly records for a value type, then compute KPIs."""
    qs = queryset.filter(value_type=value_type)
    agg = qs.aggregate(
        planned=Coalesce(Sum("plannedValue"), Value(Decimal("0.0000"))),
        earned=Coalesce(Sum("earnedValue"), Value(Decimal("0.0000"))),
    )
    return _metrics_from_totals(agg["planned"], agg["earned"])


class PlannedEarnedValuePagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


_PEV_POST_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    required=["project_name", "month", "year"],
    properties={
        "project_name": openapi.Schema(type=openapi.TYPE_STRING, example="Thane Project"),
        "projectName": openapi.Schema(type=openapi.TYPE_STRING, example="Thane Project"),
        "month": openapi.Schema(type=openapi.TYPE_INTEGER, example=6),
        "year": openapi.Schema(type=openapi.TYPE_INTEGER, example=2026),
        "scl": openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                "planned_value": openapi.Schema(type=openapi.TYPE_NUMBER, example=2000000),
                "earned_value": openapi.Schema(type=openapi.TYPE_NUMBER, example=1000000),
            },
        ),
        "contractor": openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                "planned_value": openapi.Schema(type=openapi.TYPE_NUMBER, example=0),
                "earned_value": openapi.Schema(type=openapi.TYPE_NUMBER, example=0),
            },
        ),
        "value_type": openapi.Schema(type=openapi.TYPE_STRING, enum=["SCL", "CONTRACTOR"]),
        "planned_value": openapi.Schema(type=openapi.TYPE_NUMBER, description="Flat single-record payload"),
        "earned_value": openapi.Schema(type=openapi.TYPE_NUMBER, description="Flat single-record payload"),
    },
)

_PEV_RESPONSE_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    properties={
        "success": openapi.Schema(type=openapi.TYPE_BOOLEAN, example=True),
        "message": openapi.Schema(type=openapi.TYPE_STRING),
        "data": openapi.Schema(type=openapi.TYPE_OBJECT),
    },
)


class PlannedEarnedValueViewSet(viewsets.ModelViewSet):
    """
    Planned vs Earned Value ViewSet.

    One record per (projectName, value_type, month, year).
    Supports SCL and CONTRACTOR monthly tracking within the same API.
    """

    queryset = PlannedEarnedValue.objects.all()
    serializer_class = PlannedEarnedValueSerializer
    pagination_class = PlannedEarnedValuePagination
    permission_classes = [IsAuthenticatedProjectRBAC]
    rbac_domain = RBACDomain.FINANCIAL

    def get_queryset(self):
        qs = PlannedEarnedValue.objects.all()

        project_name = self.request.query_params.get("project_name")
        if project_name:
            qs = qs.filter(projectName__icontains=project_name.strip())

        value_type = self.request.query_params.get("value_type")
        if value_type:
            qs = qs.filter(value_type=value_type.strip().upper())

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

        qs = qs.order_by("projectName", "year", "month", "value_type")
        return apply_project_rbac_to_queryset(qs, self.request, "projectName")

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

    def _clean_payload(self, request):
        return {k: v for k, v in request.data.items() if k not in _READ_ONLY_FIELDS}

    def _parse_nested_payload(self, data, instance=None):
        """
        Parse nested dashboard payload: project_name, month, year, scl, contractor.
        Returns (project_name, month, year, scl_data, contractor_data) or raises via errors dict.
        """
        errors = {}

        project_name = str(
            data.get("project_name") or data.get("projectName") or ""
        ).strip()
        if not project_name and instance is not None:
            project_name = instance.projectName

        if not project_name:
            errors["project_name"] = "project_name is required."

        month = data.get("month")
        year = data.get("year")
        if month is None and instance is not None:
            month = instance.month
        if year is None and instance is not None:
            year = instance.year

        try:
            month = int(month)
        except (TypeError, ValueError):
            errors["month"] = "month is required and must be an integer."
            month = None

        try:
            year = int(year)
        except (TypeError, ValueError):
            errors["year"] = "year is required and must be an integer."
            year = None

        if month is not None and not (1 <= month <= 12):
            errors["month"] = "month must be between 1 and 12."
        if year is not None and not (2000 <= year <= 2100):
            errors["year"] = "year must be between 2000 and 2100."

        scl_data = _nested_section_data(data, "scl", "SCL")
        contractor_data = _nested_section_data(data, "contractor", "CONTRACTOR")

        has_scl = _nested_section_present(data, "scl", "SCL")
        has_contractor = _nested_section_present(data, "contractor", "CONTRACTOR")

        if not has_scl and not has_contractor:
            errors["scl"] = (
                "Provide at least one of 'scl' or 'contractor' in the request body."
            )

        if errors:
            return None, None, None, None, None, False, False, errors

        return project_name, month, year, scl_data, contractor_data, has_scl, has_contractor, None

    def _get_existing_type_record(
        self, project_name: str, value_type: str, month: int, year: int
    ):
        return PlannedEarnedValue.objects.filter(
            projectName__iexact=project_name,
            value_type=value_type,
            month=month,
            year=year,
        ).first()

    def _upsert_type_record(
        self,
        project_name: str,
        value_type: str,
        month: int,
        year: int,
        planned: Decimal,
        earned: Decimal,
    ) -> tuple[PlannedEarnedValue, bool]:
        """Upsert one monthly record using update_or_create."""
        if planned < 0:
            raise DjangoValidationError({"plannedValue": "planned_value must be >= 0."})
        if earned < 0:
            raise DjangoValidationError({"earnedValue": "earned_value must be >= 0."})

        existing = PlannedEarnedValue.objects.filter(
            projectName__iexact=project_name,
            value_type=value_type,
            month=month,
            year=year,
        ).first()
        lookup_name = existing.projectName if existing else project_name

        record, created = PlannedEarnedValue.objects.update_or_create(
            projectName=lookup_name,
            value_type=value_type,
            month=month,
            year=year,
            defaults={
                "plannedValue": planned,
                "earnedValue": earned,
            },
        )

        if record.projectName != project_name:
            record.projectName = project_name
            record.plannedValue = planned
            record.earnedValue = earned
            record.save()

        return record, created

    def _save_nested_payload(self, request, instance=None):
        """
        Create/update SCL and/or CONTRACTOR records from nested request body.

        Only sections explicitly included in the payload are updated.
        Omitted sections are left unchanged in the database.
        """
        print("Incoming Payload:", request.data)

        (
            project_name,
            month,
            year,
            scl_data,
            contractor_data,
            has_scl,
            has_contractor,
            errors,
        ) = self._parse_nested_payload(request.data, instance=instance)
        if errors:
            return None, None, errors

        print("Updating SCL:", scl_data if has_scl else "(skipped — not in payload)")
        print(
            "Updating Contractor:",
            contractor_data if has_contractor else "(skipped — not in payload)",
        )

        created_flags = []

        if has_scl:
            if scl_data is None:
                return None, None, {"scl": "scl must be an object when provided."}
            existing_scl = self._get_existing_type_record(
                project_name,
                PlannedEarnedValue.VALUE_TYPE_SCL,
                month,
                year,
            )
            planned, earned = _extract_nested_type_values(scl_data, existing_scl)
            _, created = self._upsert_type_record(
                project_name,
                PlannedEarnedValue.VALUE_TYPE_SCL,
                month,
                year,
                planned,
                earned,
            )
            created_flags.append(created)

        if has_contractor:
            if contractor_data is None:
                return None, None, {
                    "contractor": "contractor must be an object when provided."
                }
            existing_contractor = self._get_existing_type_record(
                project_name,
                PlannedEarnedValue.VALUE_TYPE_CONTRACTOR,
                month,
                year,
            )
            planned, earned = _extract_nested_type_values(
                contractor_data, existing_contractor
            )
            _, created = self._upsert_type_record(
                project_name,
                PlannedEarnedValue.VALUE_TYPE_CONTRACTOR,
                month,
                year,
                planned,
                earned,
            )
            created_flags.append(created)

        self._invalidate_list_cache()

        response_data = _build_month_dashboard_response(project_name, month, year)
        http_status = (
            status.HTTP_201_CREATED
            if created_flags and any(created_flags)
            else status.HTTP_200_OK
        )
        message = (
            "Planned vs Earned Value records saved successfully"
            if created_flags and any(created_flags)
            else "Planned vs Earned Value records updated successfully"
        )
        return response_data, http_status, message

    def _upsert_lookup(self, payload: dict):
        """Find existing record for upsert by project + type + month + year."""
        project_name = str(
            payload.get("projectName") or payload.get("project_name") or ""
        ).strip()
        value_type = str(payload.get("value_type") or PlannedEarnedValue.VALUE_TYPE_SCL).upper()
        month = payload.get("month")
        year = payload.get("year")

        if not project_name or month is None or year is None:
            return None

        try:
            return PlannedEarnedValue.objects.get(
                projectName__iexact=project_name,
                value_type=value_type,
                month=int(month),
                year=int(year),
            )
        except (PlannedEarnedValue.DoesNotExist, TypeError, ValueError):
            return None

    @swagger_auto_schema(
        operation_summary="Create Planned vs Earned Value Record",
        request_body=_PEV_POST_SCHEMA,
        responses={201: openapi.Response("Created", _PEV_RESPONSE_SCHEMA), 400: "Validation error"},
        tags=["Planned vs Earned Value"],
    )
    def create(self, request, *args, **kwargs):
        """
        Create or update monthly record(s).

        Nested payload (dashboard): project_name, month, year, scl, contractor
        Flat payload (legacy): projectName, value_type, month, year, plannedValue, earnedValue
        """
        project_name = extract_project_name_from_data(request.data)
        enforce_project_write_by_name(
            request.user, project_name, RBACDomain.FINANCIAL
        )

        if _is_nested_payload(request.data):
            try:
                result, http_status, message = self._save_nested_payload(request)
            except DjangoValidationError as exc:
                return self._error("Validation failed", errors=exc.message_dict)
            except Exception as exc:
                logger.error(f"PlannedEarnedValue nested create error: {exc}")
                return self._error(
                    "Failed to save records",
                    errors=str(exc),
                    http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            if result is None:
                return self._error("Validation failed", errors=message)

            return self._success(message, result, http_status=http_status)

        payload = self._clean_payload(request)
        existing = self._upsert_lookup(payload)

        if existing is not None:
            serializer = PlannedEarnedValueSerializer(existing, data=payload)
        else:
            serializer = PlannedEarnedValueSerializer(data=payload)

        if not serializer.is_valid():
            return self._error("Validation failed", errors=serializer.errors)

        try:
            instance = serializer.save()
        except DjangoValidationError as exc:
            return self._error("Validation failed", errors=exc.message_dict)
        except Exception as exc:
            logger.error(f"PlannedEarnedValue create error: {exc}")
            return self._error(
                "Failed to save record",
                errors=str(exc),
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        self._invalidate_list_cache()

        http_status = status.HTTP_200_OK if existing else status.HTTP_201_CREATED
        message = (
            "Planned vs Earned Value record updated successfully"
            if existing
            else "Planned vs Earned Value record saved successfully"
        )
        return self._success(message, PlannedEarnedValueSerializer(instance).data, http_status=http_status)

    @swagger_auto_schema(
        operation_summary="Get All Planned vs Earned Value Records",
        manual_parameters=[
            openapi.Parameter("project_name", openapi.IN_QUERY, type=openapi.TYPE_STRING, required=False),
            openapi.Parameter("value_type", openapi.IN_QUERY, type=openapi.TYPE_STRING, required=False, enum=["SCL", "CONTRACTOR"]),
            openapi.Parameter("month", openapi.IN_QUERY, type=openapi.TYPE_INTEGER, required=False),
            openapi.Parameter("year", openapi.IN_QUERY, type=openapi.TYPE_INTEGER, required=False),
            openapi.Parameter("page", openapi.IN_QUERY, type=openapi.TYPE_INTEGER, required=False),
            openapi.Parameter("page_size", openapi.IN_QUERY, type=openapi.TYPE_INTEGER, required=False),
        ],
        responses={200: openapi.Response("OK", _PEV_RESPONSE_SCHEMA)},
        tags=["Planned vs Earned Value"],
    )
    def list(self, request, *args, **kwargs):
        has_filters = any(
            request.query_params.get(k)
            for k in ("project_name", "value_type", "month", "year")
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
            serializer = PlannedEarnedValueSerializer(page, many=True)
            paginated = self.get_paginated_response(serializer.data)
            payload = {
                "success": True,
                "message": "Planned vs Earned Value records retrieved successfully",
                "data": paginated.data,
            }
            if use_cache:
                cache.set(_CACHE_KEY_LIST, payload, _CACHE_TIMEOUT)
            return Response(payload)

        serializer = PlannedEarnedValueSerializer(queryset, many=True)
        payload = {
            "success": True,
            "message": "Planned vs Earned Value records retrieved successfully",
            "data": serializer.data,
        }
        if use_cache:
            cache.set(_CACHE_KEY_LIST, payload, _CACHE_TIMEOUT)
        return Response(payload)

    @swagger_auto_schema(
        operation_summary="Get Planned vs Earned Value Record by ID",
        responses={200: openapi.Response("OK", _PEV_RESPONSE_SCHEMA), 404: "Not found"},
        tags=["Planned vs Earned Value"],
    )
    def retrieve(self, request, *args, **kwargs):
        try:
            instance = PlannedEarnedValue.objects.get(pk=kwargs["pk"])
        except PlannedEarnedValue.DoesNotExist:
            return self._error(
                "Planned vs Earned Value record not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )
        return self._success(
            "Planned vs Earned Value record retrieved successfully",
            PlannedEarnedValueSerializer(instance).data,
        )

    @swagger_auto_schema(
        operation_summary="Update Planned vs Earned Value Record",
        request_body=_PEV_POST_SCHEMA,
        responses={200: openapi.Response("OK", _PEV_RESPONSE_SCHEMA), 400: "Validation error", 404: "Not found"},
        tags=["Planned vs Earned Value"],
    )
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)

        try:
            instance = PlannedEarnedValue.objects.get(pk=kwargs["pk"])
        except PlannedEarnedValue.DoesNotExist:
            return self._error(
                "Planned vs Earned Value record not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        enforce_instance_write(request.user, instance, RBACDomain.FINANCIAL)

        if _is_nested_payload(request.data):
            try:
                result, http_status, message = self._save_nested_payload(
                    request, instance=instance
                )
            except DjangoValidationError as exc:
                return self._error("Validation failed", errors=exc.message_dict)
            except Exception as exc:
                logger.error(f"PlannedEarnedValue nested update error: {exc}")
                return self._error(
                    "Failed to update records",
                    errors=str(exc),
                    http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            if result is None:
                return self._error("Validation failed", errors=message)

            return self._success(message, result, http_status=http_status)

        payload = self._clean_payload(request)
        serializer = PlannedEarnedValueSerializer(instance, data=payload, partial=partial)

        if not serializer.is_valid():
            return self._error("Validation failed", errors=serializer.errors)

        try:
            updated = serializer.save()
        except DjangoValidationError as exc:
            return self._error("Validation failed", errors=exc.message_dict)
        except Exception as exc:
            logger.error(f"PlannedEarnedValue update error: {exc}")
            return self._error(
                "Failed to update record",
                errors=str(exc),
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        self._invalidate_list_cache()
        return self._success(
            "Planned vs Earned Value record updated successfully",
            PlannedEarnedValueSerializer(updated).data,
        )

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Delete Planned vs Earned Value Record",
        responses={200: openapi.Response("OK"), 404: "Not found"},
        tags=["Planned vs Earned Value"],
    )
    def destroy(self, request, *args, **kwargs):
        try:
            instance = PlannedEarnedValue.objects.get(pk=kwargs["pk"])
        except PlannedEarnedValue.DoesNotExist:
            return self._error(
                "Planned vs Earned Value record not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        enforce_instance_write(request.user, instance, RBACDomain.FINANCIAL)

        label = f"{instance.projectName} [{instance.value_type}] {instance.month:02d}/{instance.year}"
        instance.delete()
        self._invalidate_list_cache()
        return self._success(
            f"Planned vs Earned Value record for '{label}' deleted successfully",
            {},
        )

    # -------------------------------------------------------------------------
    # LEGACY  GET /api/planned-earned-value/project/{projectName}/
    # Returns the most recently updated SCL record for backward compatibility.
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get Planned vs Earned Value by Project Name (legacy)",
        operation_description=(
            "Backward-compatible lookup. Returns the most recently updated SCL record "
            "for the project. Use the month/year dashboard endpoint for SCL + Contractor together."
        ),
        responses={200: openapi.Response("OK", _PEV_RESPONSE_SCHEMA), 404: "Not found"},
        tags=["Planned vs Earned Value"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"project/(?P<projectName>[^/.]+)",
        url_name="by-project-name",
    )
    def get_by_project_name(self, request, projectName: str = None):
        if not projectName or not projectName.strip():
            return self._error("projectName is required.")

        enforce_project_access_by_name(request.user, projectName.strip())

        instance = (
            PlannedEarnedValue.objects.filter(
                projectName__iexact=projectName.strip(),
                value_type=PlannedEarnedValue.VALUE_TYPE_SCL,
            )
            .order_by("-year", "-month", "-updated_at")
            .first()
        )

        if instance is None:
            instance = (
                PlannedEarnedValue.objects.filter(projectName__iexact=projectName.strip())
                .order_by("-year", "-month", "-updated_at")
                .first()
            )

        if instance is None:
            return self._error(
                f"No Planned vs Earned Value record found for project '{projectName}'",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        return self._success(
            "Planned vs Earned Value record retrieved successfully",
            PlannedEarnedValueSerializer(instance).data,
        )

    # -------------------------------------------------------------------------
    # DASHBOARD  GET .../project/{projectName}/month/{month}/year/{year}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get SCL + Contractor values for a project month",
        responses={200: openapi.Response("OK"), 404: "Not found"},
        tags=["Planned vs Earned Value"],
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

        records = PlannedEarnedValue.objects.filter(
            projectName__iexact=project_name,
            month=month_int,
            year=year_int,
        )

        if not records.exists():
            return self._error(
                f"No Planned vs Earned Value records found for '{project_name}' "
                f"in {month_int:02d}/{year_int}.",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        return self._success(
            f"Planned vs Earned Value for '{project_name}' ({month_int:02d}/{year_int}) retrieved successfully",
            _build_month_dashboard_response(project_name, month_int, year_int),
        )

    # -------------------------------------------------------------------------
    # YEARLY SUMMARY  GET .../project/{projectName}/year/{year}/summary/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Yearly SCL + Contractor summary (SUM aggregation)",
        responses={200: openapi.Response("OK"), 404: "Not found"},
        tags=["Planned vs Earned Value"],
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

        qs = PlannedEarnedValue.objects.filter(
            projectName__iexact=project_name,
            year=year_int,
        )

        if not qs.exists():
            return self._error(
                f"No Planned vs Earned Value records found for '{project_name}' in {year_int}.",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        return self._success(
            f"Yearly Planned vs Earned Value summary for '{project_name}' ({year_int}) retrieved successfully",
            {
                "project_name": project_name,
                "year": year_int,
                "scl": _aggregate_by_type(qs, PlannedEarnedValue.VALUE_TYPE_SCL),
                "contractor": _aggregate_by_type(qs, PlannedEarnedValue.VALUE_TYPE_CONTRACTOR),
            },
        )
