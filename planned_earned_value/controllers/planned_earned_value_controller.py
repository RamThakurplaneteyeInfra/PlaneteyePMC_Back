"""
Planned vs Earned Value Controller (ViewSet).

Handles all CRUD operations for PlannedEarnedValue records.
Uses DRF ModelViewSet for a clean, DRY implementation with a uniform
{success, message, data} response envelope on every endpoint.

Endpoints (registered via router in planned_earned_value_routes.py):
  POST   /api/planned-earned-value/                          -> create
  GET    /api/planned-earned-value/                          -> list (paginated, filterable)
  GET    /api/planned-earned-value/{id}/                     -> retrieve by ID
  PUT    /api/planned-earned-value/{id}/                     -> full update
  PATCH  /api/planned-earned-value/{id}/                     -> partial update
  DELETE /api/planned-earned-value/{id}/                     -> destroy
  GET    /api/planned-earned-value/project/{projectName}/    -> lookup by project name

Auto-calculated fields returned on every response (never sent by client):
  - variance              = earnedValue - plannedValue
  - variancePercentage    = (variance / plannedValue) * 100
  - performancePercentage = (earnedValue / plannedValue) * 100

Runtime-computed fields (not stored, derived on read):
  - schedulePerformanceIndex  (SPI = EV / PV)
  - performanceStatus         (ahead / on_track / at_risk / behind)

Scalable for future additions:
  - monthly planned vs earned tracking
  - trend analysis and baseline comparison
  - schedule variance (SV) and cost variance (CV)
  - forecasting analytics (EAC, ETC, TCPI)
  - project health indicators
  - S-curve chart data
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

from ..models.planned_earned_value import PlannedEarnedValue
from .planned_earned_value_serializer import PlannedEarnedValueSerializer

logger = logging.getLogger(__name__)

# Cache settings
_CACHE_KEY_LIST = "planned_earned_value_list"
_CACHE_TIMEOUT = 300  # 5 minutes


# =============================================================================
# Pagination
# =============================================================================

class PlannedEarnedValuePagination(PageNumberPagination):
    """Standard pagination for Planned vs Earned Value records (20/page)."""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


# =============================================================================
# Swagger schema helpers
# =============================================================================

_PEV_POST_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    required=["projectName", "plannedValue", "earnedValue"],
    properties={
        "projectName": openapi.Schema(
            type=openapi.TYPE_STRING,
            description="Unique project name",
            example="Atlas Tower",
        ),
        "plannedValue": openapi.Schema(
            type=openapi.TYPE_NUMBER,
            description="Planned Value — PV / BCWS (>= 0)",
            example=500000.00,
        ),
        "earnedValue": openapi.Schema(
            type=openapi.TYPE_NUMBER,
            description=(
                "Earned Value — EV / BCWP (>= 0). "
                "Can exceed plannedValue when project is ahead of schedule."
            ),
            example=480000.00,
        ),
    },
)

_PEV_RESPONSE_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    properties={
        "success": openapi.Schema(type=openapi.TYPE_BOOLEAN, example=True),
        "message": openapi.Schema(
            type=openapi.TYPE_STRING,
            example="Planned vs Earned Value record created successfully",
        ),
        "data": openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                "id": openapi.Schema(type=openapi.TYPE_INTEGER, example=1),
                "projectName": openapi.Schema(
                    type=openapi.TYPE_STRING, example="Atlas Tower"
                ),
                "plannedValue": openapi.Schema(
                    type=openapi.TYPE_NUMBER, example=500000.00
                ),
                "earnedValue": openapi.Schema(
                    type=openapi.TYPE_NUMBER, example=480000.00
                ),
                "variance": openapi.Schema(
                    type=openapi.TYPE_NUMBER,
                    description="Auto-calculated: EV - PV (negative = behind schedule)",
                    example=-20000.00,
                ),
                "variancePercentage": openapi.Schema(
                    type=openapi.TYPE_NUMBER,
                    description="Auto-calculated: (variance / plannedValue) * 100",
                    example=-4.00,
                ),
                "performancePercentage": openapi.Schema(
                    type=openapi.TYPE_NUMBER,
                    description="Auto-calculated: (earnedValue / plannedValue) * 100",
                    example=96.00,
                ),
                "schedulePerformanceIndex": openapi.Schema(
                    type=openapi.TYPE_NUMBER,
                    description="SPI = EV / PV (> 1 = ahead, < 1 = behind)",
                    example=0.96,
                ),
                "performanceStatus": openapi.Schema(
                    type=openapi.TYPE_STRING,
                    description="ahead | on_track | at_risk | behind",
                    example="on_track",
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
# ViewSet
# =============================================================================

class PlannedEarnedValueViewSet(viewsets.ModelViewSet):
    """
    Planned vs Earned Value ViewSet.

    One record per project — tracks cumulative PV vs EV for dashboard KPIs,
    gauge meters, and performance charts.

    All calculated fields are auto-computed by the model on every save.
    Clients only need to send: projectName, plannedValue, earnedValue.

    Performance status thresholds (performancePercentage):
      >= 100%  → 'ahead'
      >= 90%   → 'on_track'
      >= 75%   → 'at_risk'
      < 75%    → 'behind'
    """

    queryset = PlannedEarnedValue.objects.all()
    serializer_class = PlannedEarnedValueSerializer
    permission_classes = [AllowAny]
    pagination_class = PlannedEarnedValuePagination

    # -------------------------------------------------------------------------
    # Queryset optimisation
    # -------------------------------------------------------------------------

    def get_queryset(self):
        """
        Return optimised queryset.
        Supports optional ?project_name= filter for project-wise filtering.
        """
        qs = PlannedEarnedValue.objects.only(
            "id",
            "projectName",
            "plannedValue",
            "earnedValue",
            "variance",
            "variancePercentage",
            "performancePercentage",
            "created_at",
            "updated_at",
        )

        # Optional project-wise filter: ?project_name=Atlas
        project_name = self.request.query_params.get("project_name")
        if project_name:
            qs = qs.filter(projectName__icontains=project_name.strip())

        return qs

    # -------------------------------------------------------------------------
    # Response helpers
    # -------------------------------------------------------------------------

    def _invalidate_list_cache(self):
        """Invalidate the cached list whenever data changes."""
        cache.delete(_CACHE_KEY_LIST)

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
    # CREATE  POST /api/planned-earned-value/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Create Planned vs Earned Value Record",
        operation_description=(
            "Create a new Planned vs Earned Value record for a project.\n\n"
            "**Auto-calculated fields (do not send):**\n"
            "- `variance` = earnedValue − plannedValue\n"
            "- `variancePercentage` = (variance / plannedValue) × 100\n"
            "- `performancePercentage` = (earnedValue / plannedValue) × 100\n\n"
            "**earnedValue can exceed plannedValue** (project ahead of schedule).\n"
            "Both values must be >= 0."
        ),
        request_body=_PEV_POST_SCHEMA,
        responses={
            201: openapi.Response("Created", _PEV_RESPONSE_SCHEMA),
            400: "Validation error",
        },
        tags=["Planned vs Earned Value"],
    )
    def create(self, request, *args, **kwargs):
        """
        Create or update a Planned vs Earned Value record (upsert by projectName).

        If a record already exists for the given projectName it is updated
        in-place rather than returning a 500 uniqueness error.
        Auto-calculates variance, variancePercentage, performancePercentage.
        """
        project_name = str(request.data.get("projectName", "")).strip()

        # Strip read-only / auto-calculated fields the frontend should not send
        _READ_ONLY = {"variance", "variancePercentage", "performancePercentage", "schedulePerformanceIndex", "performanceStatus", "id", "created_at", "updated_at"}
        payload = {k: v for k, v in request.data.items() if k not in _READ_ONLY}

        # Upsert: if a record already exists for this project, update it.
        existing = None
        if project_name:
            try:
                existing = PlannedEarnedValue.objects.get(
                    projectName__iexact=project_name
                )
            except PlannedEarnedValue.DoesNotExist:
                pass

        if existing is not None:
            serializer = PlannedEarnedValueSerializer(
                existing, data=payload, partial=False
            )
        else:
            serializer = PlannedEarnedValueSerializer(data=payload)

        if not serializer.is_valid():
            return self._error("Invalid data provided", errors=serializer.errors)

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
            else "Planned vs Earned Value record created successfully"
        )

        return self._success(
            message,
            PlannedEarnedValueSerializer(instance).data,
            http_status=http_status,
        )

    # -------------------------------------------------------------------------
    # LIST  GET /api/planned-earned-value/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get All Planned vs Earned Value Records",
        operation_description=(
            "Retrieve all records. "
            "Supports optional ?project_name= filter and pagination."
        ),
        manual_parameters=[
            openapi.Parameter(
                "project_name",
                openapi.IN_QUERY,
                description="Filter by project name (case-insensitive partial match)",
                type=openapi.TYPE_STRING,
                required=False,
            ),
            openapi.Parameter(
                "page",
                openapi.IN_QUERY,
                description="Page number",
                type=openapi.TYPE_INTEGER,
                required=False,
            ),
            openapi.Parameter(
                "page_size",
                openapi.IN_QUERY,
                description="Records per page (max 100)",
                type=openapi.TYPE_INTEGER,
                required=False,
            ),
        ],
        responses={200: openapi.Response("OK", _PEV_RESPONSE_SCHEMA)},
        tags=["Planned vs Earned Value"],
    )
    def list(self, request, *args, **kwargs):
        """
        Return all Planned vs Earned Value records (paginated).
        Results are cached for 5 minutes; cache is invalidated on any write.
        """
        project_filter = request.query_params.get("project_name")
        page_param = request.query_params.get("page", "1")
        use_cache = not project_filter and page_param == "1"

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

    # -------------------------------------------------------------------------
    # RETRIEVE  GET /api/planned-earned-value/{id}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get Planned vs Earned Value Record by ID",
        responses={
            200: openapi.Response("OK", _PEV_RESPONSE_SCHEMA),
            404: "Not found",
        },
        tags=["Planned vs Earned Value"],
    )
    def retrieve(self, request, *args, **kwargs):
        """Retrieve a single record by its primary key."""
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

    # -------------------------------------------------------------------------
    # UPDATE  PUT /api/planned-earned-value/{id}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Update Planned vs Earned Value Record",
        operation_description=(
            "Full or partial update of a record. "
            "variance, variancePercentage, and performancePercentage "
            "are recalculated automatically after every update."
        ),
        request_body=_PEV_POST_SCHEMA,
        responses={
            200: openapi.Response("OK", _PEV_RESPONSE_SCHEMA),
            400: "Validation error",
            404: "Not found",
        },
        tags=["Planned vs Earned Value"],
    )
    def update(self, request, *args, **kwargs):
        """
        Full update (PUT) of a Planned vs Earned Value record.
        All calculated fields are recomputed after update.
        """
        partial = kwargs.pop("partial", False)

        try:
            instance = PlannedEarnedValue.objects.get(pk=kwargs["pk"])
        except PlannedEarnedValue.DoesNotExist:
            return self._error(
                "Planned vs Earned Value record not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        _READ_ONLY = {"variance", "variancePercentage", "performancePercentage", "schedulePerformanceIndex", "performanceStatus", "id", "created_at", "updated_at"}
        payload = {k: v for k, v in request.data.items() if k not in _READ_ONLY}

        serializer = PlannedEarnedValueSerializer(
            instance, data=payload, partial=partial
        )

        if not serializer.is_valid():
            return self._error("Invalid data provided", errors=serializer.errors)

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
        """PATCH — partial update, delegates to update() with partial=True."""
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    # -------------------------------------------------------------------------
    # DELETE  DELETE /api/planned-earned-value/{id}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Delete Planned vs Earned Value Record",
        responses={
            200: openapi.Response("OK"),
            404: "Not found",
        },
        tags=["Planned vs Earned Value"],
    )
    def destroy(self, request, *args, **kwargs):
        """Delete a record by its primary key."""
        try:
            instance = PlannedEarnedValue.objects.get(pk=kwargs["pk"])
        except PlannedEarnedValue.DoesNotExist:
            return self._error(
                "Planned vs Earned Value record not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        project_name = instance.projectName
        instance.delete()
        self._invalidate_list_cache()

        return self._success(
            f"Planned vs Earned Value record for '{project_name}' deleted successfully",
            {},
        )

    # -------------------------------------------------------------------------
    # CUSTOM ACTION  GET /api/planned-earned-value/project/{projectName}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get Planned vs Earned Value Record by Project Name",
        operation_description=(
            "Retrieve a record using the exact project name (case-insensitive). "
            "Returns all KPI fields including SPI and performanceStatus — "
            "ready for dashboard gauge meters and performance cards."
        ),
        responses={
            200: openapi.Response("OK", _PEV_RESPONSE_SCHEMA),
            404: "Not found",
        },
        tags=["Planned vs Earned Value"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"project/(?P<projectName>[^/.]+)",
        url_name="by-project-name",
    )
    def get_by_project_name(self, request, projectName: str = None):
        """
        Retrieve a Planned vs Earned Value record by exact project name.
        Case-insensitive lookup. Ideal for dashboard KPI card and gauge integration.
        """
        if not projectName or not projectName.strip():
            return self._error("projectName is required.")

        try:
            instance = PlannedEarnedValue.objects.get(
                projectName__iexact=projectName.strip()
            )
        except PlannedEarnedValue.DoesNotExist:
            return self._error(
                f"No Planned vs Earned Value record found for project '{projectName}'",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        return self._success(
            "Planned vs Earned Value record retrieved successfully",
            PlannedEarnedValueSerializer(instance).data,
        )
