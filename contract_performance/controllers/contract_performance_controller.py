"""
Contract Performance Controller (ViewSet).

Handles all CRUD operations for ContractPerformance records.
Uses DRF ModelViewSet with a uniform {success, message, data} response envelope.

Standard endpoints (via router):
  POST   /api/contract-performance/                          -> create
  GET    /api/contract-performance/                          -> list (paginated, filterable)
  GET    /api/contract-performance/{id}/                     -> retrieve by ID
  PUT    /api/contract-performance/{id}/                     -> full update
  PATCH  /api/contract-performance/{id}/                     -> partial update
  DELETE /api/contract-performance/{id}/                     -> destroy

Custom filter endpoint (via @action):
  GET    /api/contract-performance/project/{projectName}/    -> lookup by project name

Auto-calculated fields (never send, always returned):
  - variance              = billedValue - actualReceiptValue
  - variancePercentage    = (variance / billedValue) * 100
  - performancePercentage = (actualReceiptValue / billedValue) * 100

Runtime-computed fields (not stored, derived on read):
  - collectionEfficiency  (actualReceiptValue / billedValue)
  - performanceStatus     (excellent / good / average / poor)

Scalable for future additions:
  - Monthly contract performance tracking
  - Collection efficiency analytics
  - Payment trends and recovery forecasting
  - Project financial health indicators
"""

import logging

from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from accounts.permissions import IsAuthenticatedProjectRBAC
from accounts.rbac import RBACDomain, resolve_project
from accounts.rbac_checks import (
    apply_project_rbac_to_queryset,
    enforce_instance_write,
    enforce_project_access_by_name,
    enforce_project_write_by_name,
)

from ..models.contract_performance import ContractPerformance
from core.cache_keys import build_rbac_list_cache_key, invalidate_list_cache
from services.billing_update_notifications import (
    BillingAction,
    BillingModule,
    schedule_billing_update_notification,
    schedule_billing_update_notification_for_instance,
)
from .contract_performance_serializer import ContractPerformanceSerializer

logger = logging.getLogger(__name__)

# Cache settings
_CACHE_KEY_LIST = "contract_performance_list"
_CACHE_TIMEOUT = 300  # 5 minutes


# =============================================================================
# Pagination
# =============================================================================

class ContractPerformancePagination(PageNumberPagination):
    """Standard pagination for contract performance records (20/page)."""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


# =============================================================================
# Swagger schema helpers
# =============================================================================

_CP_POST_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    required=["projectName", "billedValue", "actualReceiptValue"],
    properties={
        "projectName": openapi.Schema(
            type=openapi.TYPE_STRING,
            description="Unique project name",
            example="Atlas Tower",
        ),
        "billedValue": openapi.Schema(
            type=openapi.TYPE_NUMBER,
            description="Total billed value (>= 0)",
            example=140000000.00,
        ),
        "actualReceiptValue": openapi.Schema(
            type=openapi.TYPE_NUMBER,
            description="Actual receipt / collection value (>= 0)",
            example=120000000.00,
        ),
    },
)

_CP_RESPONSE_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    properties={
        "success": openapi.Schema(type=openapi.TYPE_BOOLEAN, example=True),
        "message": openapi.Schema(
            type=openapi.TYPE_STRING,
            example="Contract performance record created successfully",
        ),
        "data": openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                "id": openapi.Schema(type=openapi.TYPE_INTEGER, example=1),
                "projectName": openapi.Schema(
                    type=openapi.TYPE_STRING, example="Atlas Tower"
                ),
                "billedValue": openapi.Schema(
                    type=openapi.TYPE_NUMBER, example=140000000.00
                ),
                "actualReceiptValue": openapi.Schema(
                    type=openapi.TYPE_NUMBER, example=120000000.00
                ),
                "variance": openapi.Schema(
                    type=openapi.TYPE_NUMBER,
                    description="Auto-calculated: billedValue - actualReceiptValue",
                    example=20000000.00,
                ),
                "variancePercentage": openapi.Schema(
                    type=openapi.TYPE_NUMBER,
                    description="Auto-calculated: (variance / billedValue) * 100",
                    example=14.29,
                ),
                "performancePercentage": openapi.Schema(
                    type=openapi.TYPE_NUMBER,
                    description="Auto-calculated: (actualReceiptValue / billedValue) * 100",
                    example=85.71,
                ),
                "collectionEfficiency": openapi.Schema(
                    type=openapi.TYPE_NUMBER,
                    description="actualReceiptValue / billedValue",
                    example=0.8571,
                ),
                "performanceStatus": openapi.Schema(
                    type=openapi.TYPE_STRING,
                    description="excellent | good | average | poor",
                    example="average",
                ),
                "created_at": openapi.Schema(
                    type=openapi.TYPE_STRING, example="2024-01-15T10:30:00Z"
                ),
                "updated_at": openapi.Schema(
                    type=openapi.TYPE_STRING, example="2024-01-15T10:30:00Z"
                ),
            },
        ),
    },
)


# =============================================================================
# Reusable utility functions
# =============================================================================

def _build_queryset(project_name: str = None, search: str = None):
    """
    Reusable queryset builder with optional filters.

    Args:
        project_name : partial, case-insensitive project name filter
        search       : free-text search across projectName
    """
    qs = ContractPerformance.objects.only(
        "id",
        "projectName",
        "billedValue",
        "actualReceiptValue",
        "variance",
        "variancePercentage",
        "performancePercentage",
        "created_at",
        "updated_at",
    )

    if project_name:
        qs = qs.filter(projectName__icontains=project_name.strip())

    if search:
        qs = qs.filter(projectName__icontains=search.strip())

    return qs


# =============================================================================
# ViewSet
# =============================================================================

class ContractPerformanceViewSet(viewsets.ModelViewSet):
    """
    Contract Performance ViewSet.

    One record per project — tracks cumulative billing vs receipt KPIs
    for dashboard performance gauges and financial analytics.

    All calculated fields are auto-computed by the model on every save.
    Clients only need to send: projectName, billedValue, actualReceiptValue.

    Performance status thresholds (performancePercentage):
      >= 100%  → 'excellent'
      >= 90%   → 'good'
      >= 75%   → 'average'
      < 75%    → 'poor'
    """

    queryset = ContractPerformance.objects.all()
    serializer_class = ContractPerformanceSerializer
    pagination_class = ContractPerformancePagination
    permission_classes = [IsAuthenticatedProjectRBAC]
    rbac_domain = RBACDomain.FINANCIAL

    # -------------------------------------------------------------------------
    # Queryset
    # -------------------------------------------------------------------------

    def get_queryset(self):
        """
        Return optimised queryset with optional query-param filters.

        Supported query params:
          ?project_name= — partial, case-insensitive project name filter
          ?search=       — free-text search across projectName
        """
        qs = _build_queryset(
            project_name=self.request.query_params.get("project_name"),
            search=self.request.query_params.get("search"),
        )
        return apply_project_rbac_to_queryset(qs, self.request, "projectName")

    # -------------------------------------------------------------------------
    # Response helpers
    # -------------------------------------------------------------------------

    def _invalidate_cache(self):
        """Invalidate all contract performance list caches on any write."""
        invalidate_list_cache(_CACHE_KEY_LIST)

    def _success(self, message: str, data, http_status=status.HTTP_200_OK):
        """Uniform success response: {success, message, data}."""
        return Response(
            {"success": True, "message": message, "data": data},
            status=http_status,
        )

    def _error(
        self,
        message: str,
        errors=None,
        http_status=status.HTTP_400_BAD_REQUEST,
    ):
        """Uniform error response: {success, message, errors?}."""
        payload = {"success": False, "message": message}
        if errors is not None:
            payload["errors"] = errors
        return Response(payload, status=http_status)

    # -------------------------------------------------------------------------
    # CREATE  POST /api/contract-performance/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Create Contract Performance Record",
        operation_description=(
            "Create a new contract performance record for a project.\n\n"
            "**Auto-calculated fields (do not send):**\n"
            "- `variance` = billedValue − actualReceiptValue\n"
            "- `variancePercentage` = (variance / billedValue) × 100\n"
            "- `performancePercentage` = (actualReceiptValue / billedValue) × 100\n\n"
            "Both values must be >= 0. "
            "actualReceiptValue can exceed billedValue (over-collection)."
        ),
        request_body=_CP_POST_SCHEMA,
        responses={
            201: openapi.Response("Created", _CP_RESPONSE_SCHEMA),
            400: "Validation error",
        },
        tags=["Contract Performance"],
    )
    def create(self, request, *args, **kwargs):
        """
        Create or update a contract performance record (upsert by projectName).

        If a record already exists for the given projectName it is updated
        in-place rather than returning a 500 uniqueness error.
        Auto-calculates variance, variancePercentage, performancePercentage.

        Accepts both camelCase and snake_case field names from the frontend.
        """
        # Accept both camelCase and snake_case for projectName lookup
        project_name = str(
            request.data.get("projectName")
            or request.data.get("project_name")
            or ""
        ).strip()

        enforce_project_write_by_name(
            request.user, project_name, RBACDomain.FINANCIAL
        )

        # Strip read-only / auto-calculated fields the frontend should not send
        _READ_ONLY = {
            "variance", "variancePercentage", "performancePercentage",
            "collectionEfficiency", "performanceStatus",
            "id", "created_at", "updated_at",
        }
        payload = {k: v for k, v in request.data.items() if k not in _READ_ONLY}

        logger.debug("ContractPerformance create payload: %s", payload)

        # Upsert: if a record already exists for this project, update it.
        existing = None
        if project_name:
            try:
                existing = ContractPerformance.objects.get(
                    projectName__iexact=project_name
                )
            except ContractPerformance.DoesNotExist:
                pass

        if existing is not None:
            serializer = ContractPerformanceSerializer(
                existing, data=payload, partial=False
            )
        else:
            serializer = ContractPerformanceSerializer(data=payload)

        if not serializer.is_valid():
            return self._error("Invalid data provided", errors=serializer.errors)

        try:
            instance = serializer.save()
        except DjangoValidationError as exc:
            return self._error("Validation failed", errors=exc.message_dict)
        except Exception as exc:
            logger.error(f"ContractPerformance create error: {exc}")
            return self._error(
                "Failed to save contract performance record",
                errors=str(exc),
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        action = BillingAction.UPDATE if existing else BillingAction.CREATE
        schedule_billing_update_notification(
            request.user,
            resolve_project(project_name),
            BillingModule.CONTRACT_PERFORMANCE,
            action,
        )

        self._invalidate_cache()

        http_status = status.HTTP_200_OK if existing else status.HTTP_201_CREATED
        message = (
            "Contract performance record updated successfully"
            if existing
            else "Contract performance record created successfully"
        )

        return self._success(
            message,
            ContractPerformanceSerializer(instance).data,
            http_status=http_status,
        )

    # -------------------------------------------------------------------------
    # LIST  GET /api/contract-performance/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get All Contract Performance Records",
        operation_description=(
            "Retrieve all contract performance records.\n\n"
            "**Supports filtering:**\n"
            "- `?project_name=` — partial, case-insensitive project name\n"
            "- `?search=` — free-text search across project names"
        ),
        manual_parameters=[
            openapi.Parameter(
                "project_name", openapi.IN_QUERY,
                description="Filter by project name (partial, case-insensitive)",
                type=openapi.TYPE_STRING, required=False,
            ),
            openapi.Parameter(
                "search", openapi.IN_QUERY,
                description="Free-text search across project names",
                type=openapi.TYPE_STRING, required=False,
            ),
            openapi.Parameter(
                "page", openapi.IN_QUERY,
                description="Page number",
                type=openapi.TYPE_INTEGER, required=False,
            ),
            openapi.Parameter(
                "page_size", openapi.IN_QUERY,
                description="Records per page (max 100)",
                type=openapi.TYPE_INTEGER, required=False,
            ),
        ],
        responses={200: openapi.Response("OK", _CP_RESPONSE_SCHEMA)},
        tags=["Contract Performance"],
    )
    def list(self, request, *args, **kwargs):
        """
        Return all contract performance records (paginated, filterable).
        Results are cached for 5 minutes; cache is invalidated on any write.
        """
        project_filter = request.query_params.get("project_name")
        search_filter = request.query_params.get("search")
        page_param = request.query_params.get("page", "1")

        use_cache = not any([project_filter, search_filter]) and page_param == "1"
        cache_key = build_rbac_list_cache_key(
            _CACHE_KEY_LIST,
            request,
            extra_parts=[f"p:{project_filter or ''}", f"pg:{page_param}"],
            use_query_string=False,
        )

        if use_cache:
            cached = cache.get(cache_key)
            if cached is not None:
                return Response(cached)

        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = ContractPerformanceSerializer(page, many=True)
            paginated = self.get_paginated_response(serializer.data)
            payload = {
                "success": True,
                "message": "Contract performance records retrieved successfully",
                "data": paginated.data,
            }
            if use_cache:
                cache.set(cache_key, payload, _CACHE_TIMEOUT)
            return Response(payload)

        serializer = ContractPerformanceSerializer(queryset, many=True)
        payload = {
            "success": True,
            "message": "Contract performance records retrieved successfully",
            "data": serializer.data,
        }
        if use_cache:
            cache.set(cache_key, payload, _CACHE_TIMEOUT)
        return Response(payload)

    # -------------------------------------------------------------------------
    # RETRIEVE  GET /api/contract-performance/{id}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get Contract Performance Record by ID",
        responses={
            200: openapi.Response("OK", _CP_RESPONSE_SCHEMA),
            404: "Not found",
        },
        tags=["Contract Performance"],
    )
    def retrieve(self, request, *args, **kwargs):
        """Retrieve a single contract performance record by its primary key."""
        try:
            instance = ContractPerformance.objects.get(pk=kwargs["pk"])
        except ContractPerformance.DoesNotExist:
            return self._error(
                "Contract performance record not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        return self._success(
            "Contract performance record retrieved successfully",
            ContractPerformanceSerializer(instance).data,
        )

    # -------------------------------------------------------------------------
    # UPDATE  PUT /api/contract-performance/{id}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Update Contract Performance Record",
        operation_description=(
            "Full or partial update of a contract performance record. "
            "All calculated fields are recomputed automatically after update."
        ),
        request_body=_CP_POST_SCHEMA,
        responses={
            200: openapi.Response("OK", _CP_RESPONSE_SCHEMA),
            400: "Validation error",
            404: "Not found",
        },
        tags=["Contract Performance"],
    )
    def update(self, request, *args, **kwargs):
        """
        Full update (PUT) of a contract performance record.
        All calculated fields are recomputed after update.
        """
        partial = kwargs.pop("partial", False)

        try:
            instance = ContractPerformance.objects.get(pk=kwargs["pk"])
        except ContractPerformance.DoesNotExist:
            return self._error(
                "Contract performance record not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        enforce_instance_write(request.user, instance, RBACDomain.FINANCIAL)

        _READ_ONLY = {"variance", "variancePercentage", "performancePercentage", "collectionEfficiency", "performanceStatus", "id", "created_at", "updated_at"}
        payload = {k: v for k, v in request.data.items() if k not in _READ_ONLY}

        serializer = ContractPerformanceSerializer(
            instance, data=payload, partial=partial
        )

        if not serializer.is_valid():
            return self._error("Invalid data provided", errors=serializer.errors)

        try:
            updated = serializer.save()
        except DjangoValidationError as exc:
            return self._error("Validation failed", errors=exc.message_dict)
        except Exception as exc:
            logger.error(f"ContractPerformance update error: {exc}")
            return self._error(
                "Failed to update contract performance record",
                errors=str(exc),
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        schedule_billing_update_notification_for_instance(
            request.user,
            updated,
            BillingModule.CONTRACT_PERFORMANCE,
            BillingAction.UPDATE,
        )

        self._invalidate_cache()

        return self._success(
            "Contract performance updated successfully",
            ContractPerformanceSerializer(updated).data,
        )

    def partial_update(self, request, *args, **kwargs):
        """PATCH — partial update, delegates to update() with partial=True."""
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    # -------------------------------------------------------------------------
    # DELETE  DELETE /api/contract-performance/{id}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Delete Contract Performance Record",
        responses={
            200: openapi.Response("OK"),
            404: "Not found",
        },
        tags=["Contract Performance"],
    )
    def destroy(self, request, *args, **kwargs):
        """Delete a contract performance record by its primary key."""
        try:
            instance = ContractPerformance.objects.get(pk=kwargs["pk"])
        except ContractPerformance.DoesNotExist:
            return self._error(
                "Contract performance record not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        enforce_instance_write(request.user, instance, RBACDomain.FINANCIAL)

        project_name = instance.projectName
        schedule_billing_update_notification_for_instance(
            request.user,
            instance,
            BillingModule.CONTRACT_PERFORMANCE,
            BillingAction.DELETE,
        )
        instance.delete()
        self._invalidate_cache()

        return self._success(
            f"Contract performance record for '{project_name}' deleted successfully",
            {},
        )

    # -------------------------------------------------------------------------
    # CUSTOM ACTION  GET /api/contract-performance/project/{projectName}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get Contract Performance Record by Project Name",
        operation_description=(
            "Retrieve a contract performance record using the exact project name "
            "(case-insensitive). Returns all KPI fields including "
            "collectionEfficiency and performanceStatus — ready for dashboard "
            "gauge meters and performance cards."
        ),
        responses={
            200: openapi.Response("OK", _CP_RESPONSE_SCHEMA),
            404: "Not found",
        },
        tags=["Contract Performance"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"project/(?P<projectName>[^/.]+)",
        url_name="by-project-name",
    )
    def get_by_project_name(self, request, projectName: str = None):
        """
        Retrieve a contract performance record by exact project name.
        Case-insensitive lookup. Ideal for dashboard KPI card integration.
        """
        if not projectName or not projectName.strip():
            return self._error("projectName is required.")

        enforce_project_access_by_name(request.user, projectName.strip())

        try:
            instance = ContractPerformance.objects.get(
                projectName__iexact=projectName.strip()
            )
        except ContractPerformance.DoesNotExist:
            return self._error(
                f"No contract performance record found for project '{projectName}'",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        return self._success(
            "Contract performance record retrieved successfully",
            ContractPerformanceSerializer(instance).data,
        )
