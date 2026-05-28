"""
Monthly Construction Progress Controller (ViewSet).

Handles all CRUD operations for ConstructionProgress records.
Uses DRF ModelViewSet with a uniform {success, message, data} response envelope.

Endpoints (mounted at /api/ in backend/urls.py):
  POST   /api/construction-progress/                               -> create
  GET    /api/construction-progress/                               -> list
  GET    /api/construction-progress/{id}/                          -> retrieve
  PUT    /api/construction-progress/{id}/                          -> full update
  PATCH  /api/construction-progress/{id}/                          -> partial update
  DELETE /api/construction-progress/{id}/                          -> destroy

Custom filter endpoints (via @action):
  GET    /api/construction-progress/project/{projectName}/         -> by project
  GET    /api/construction-progress/month/{progressMonth}/         -> by month

Auto-calculated fields (never send, always returned):
  - variance              = actualProgress - plannedProgress
  - performancePercentage = (actualProgress / plannedProgress) * 100

Runtime-computed field (not stored):
  - progressStatus  (on_track / slight_delay / delayed / critical)

Frontend payload (camelCase or snake_case both accepted):
  {
    "projectName":     "Thane Project",
    "progressMonth":   "2026-05",
    "plannedProgress": 45,
    "actualProgress":  40,
    "remarks":         "Progress delayed due to rain"   // optional
  }
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

from ..models.construction_progress import ConstructionProgress
from .construction_progress_serializer import ConstructionProgressSerializer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
_CACHE_KEY_LIST = "construction_progress_list"
_CACHE_TIMEOUT = 300  # 5 minutes

# ---------------------------------------------------------------------------
# snake_case → camelCase normalisation
# Accepts payloads from frontends that send snake_case field names.
# ---------------------------------------------------------------------------
_SNAKE_TO_CAMEL = {
    "project_name": "projectName",
    "progress_month": "progressMonth",
    "planned_progress": "plannedProgress",
    "actual_progress": "actualProgress",
}


def _normalize_payload(data: dict) -> dict:
    """Map any snake_case keys to the camelCase names the serializer expects."""
    return {_SNAKE_TO_CAMEL.get(k, k): v for k, v in data.items()}


# ---------------------------------------------------------------------------
# Read-only fields the frontend must never send
# ---------------------------------------------------------------------------
_READ_ONLY = {
    "id",
    "variance",
    "performancePercentage",
    "progressStatus",
    "created_at",
    "updated_at",
}


# =============================================================================
# Pagination
# =============================================================================

class ConstructionProgressPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


# =============================================================================
# Swagger schema helpers
# =============================================================================

_CP_POST_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    required=["projectName", "progressMonth", "plannedProgress", "actualProgress"],
    properties={
        "projectName": openapi.Schema(
            type=openapi.TYPE_STRING,
            description="Project name",
            example="Thane Project",
        ),
        "progressMonth": openapi.Schema(
            type=openapi.TYPE_STRING,
            description="Month in YYYY-MM format",
            example="2026-05",
        ),
        "plannedProgress": openapi.Schema(
            type=openapi.TYPE_NUMBER,
            description="Planned progress percentage (0–100)",
            example=45.0,
        ),
        "actualProgress": openapi.Schema(
            type=openapi.TYPE_NUMBER,
            description="Actual progress percentage (0–100)",
            example=40.0,
        ),
        "remarks": openapi.Schema(
            type=openapi.TYPE_STRING,
            description="Optional remarks",
            example="Progress delayed due to rain",
        ),
    },
)

_CP_RESPONSE_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    properties={
        "success": openapi.Schema(type=openapi.TYPE_BOOLEAN, example=True),
        "message": openapi.Schema(type=openapi.TYPE_STRING),
        "data": openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                "id": openapi.Schema(type=openapi.TYPE_INTEGER, example=1),
                "projectName": openapi.Schema(type=openapi.TYPE_STRING, example="Thane Project"),
                "progressMonth": openapi.Schema(type=openapi.TYPE_STRING, example="2026-05"),
                "plannedProgress": openapi.Schema(type=openapi.TYPE_NUMBER, example=45.0),
                "actualProgress": openapi.Schema(type=openapi.TYPE_NUMBER, example=40.0),
                "variance": openapi.Schema(
                    type=openapi.TYPE_NUMBER,
                    description="Auto-calculated: actualProgress - plannedProgress",
                    example=-5.0,
                ),
                "performancePercentage": openapi.Schema(
                    type=openapi.TYPE_NUMBER,
                    description="Auto-calculated: (actualProgress / plannedProgress) * 100",
                    example=88.89,
                ),
                "progressStatus": openapi.Schema(
                    type=openapi.TYPE_STRING,
                    description="on_track | slight_delay | delayed | critical",
                    example="slight_delay",
                ),
                "remarks": openapi.Schema(type=openapi.TYPE_STRING, example="Progress delayed due to rain"),
                "created_at": openapi.Schema(type=openapi.TYPE_STRING, example="2026-05-01T10:00:00Z"),
                "updated_at": openapi.Schema(type=openapi.TYPE_STRING, example="2026-05-28T12:00:00Z"),
            },
        ),
    },
)


# =============================================================================
# ViewSet
# =============================================================================

class ConstructionProgressViewSet(viewsets.ModelViewSet):
    """
    Monthly Construction Progress ViewSet.

    One record per project per month — tracks planned vs actual progress
    for dashboard charts, S-curve analytics, and KPI cards.

    All calculated fields are auto-computed by the model on every save.
    Clients only need to send:
      projectName, progressMonth, plannedProgress, actualProgress, remarks (optional).

    Progress status thresholds (performancePercentage):
      >= 100% → 'on_track'
      >= 80%  → 'slight_delay'
      >= 60%  → 'delayed'
      < 60%   → 'critical'
    """

    queryset = ConstructionProgress.objects.all()
    serializer_class = ConstructionProgressSerializer
    permission_classes = [AllowAny]
    pagination_class = ConstructionProgressPagination

    # -------------------------------------------------------------------------
    # Queryset
    # -------------------------------------------------------------------------

    def get_queryset(self):
        """
        Filterable queryset.

        Supported query params:
          ?project_name=   — partial, case-insensitive project name filter
          ?progress_month= — exact month filter (YYYY-MM)
          ?search=         — free-text search across projectName
        """
        qs = ConstructionProgress.objects.all()

        project_name = self.request.query_params.get("project_name")
        if project_name:
            qs = qs.filter(projectName__icontains=project_name.strip())

        progress_month = self.request.query_params.get("progress_month")
        if progress_month:
            qs = qs.filter(progressMonth=progress_month.strip())

        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(projectName__icontains=search.strip())

        return qs.order_by("projectName", "progressMonth")

    # -------------------------------------------------------------------------
    # Response helpers
    # -------------------------------------------------------------------------

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

    # -------------------------------------------------------------------------
    # CREATE  POST /api/construction-progress/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Create Monthly Construction Progress Record",
        operation_description=(
            "Create a new monthly progress record for a project.\n\n"
            "**One record per project per month** — duplicate month entries are rejected.\n\n"
            "**Auto-calculated fields (do not send):**\n"
            "- `variance` = actualProgress − plannedProgress\n"
            "- `performancePercentage` = (actualProgress / plannedProgress) × 100\n\n"
            "**progressMonth** must be in `YYYY-MM` format."
        ),
        request_body=_CP_POST_SCHEMA,
        responses={
            201: openapi.Response("Created", _CP_RESPONSE_SCHEMA),
            400: "Validation error",
        },
        tags=["Construction Progress"],
    )
    def create(self, request, *args, **kwargs):
        """
        Create a new monthly construction progress record.

        Duplicate (projectName + progressMonth) entries are rejected with a
        clear error message directing the client to use PUT for updates.
        """
        payload = {k: v for k, v in _normalize_payload(request.data).items() if k not in _READ_ONLY}

        serializer = ConstructionProgressSerializer(data=payload)
        if not serializer.is_valid():
            return self._error("Invalid data provided", errors=serializer.errors)

        try:
            instance = serializer.save()
        except DjangoValidationError as exc:
            return self._error("Validation failed", errors=exc.message_dict)
        except Exception as exc:
            logger.error(f"ConstructionProgress create error: {exc}")
            return self._error(
                "Failed to save construction progress record",
                errors=str(exc),
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        self._invalidate_cache()
        return self._success(
            "Construction progress saved successfully",
            ConstructionProgressSerializer(instance).data,
            http_status=status.HTTP_201_CREATED,
        )

    # -------------------------------------------------------------------------
    # LIST  GET /api/construction-progress/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get All Construction Progress Records",
        operation_description=(
            "Retrieve all monthly progress records.\n\n"
            "**Supports filtering:**\n"
            "- `?project_name=` — partial, case-insensitive project name\n"
            "- `?progress_month=` — exact month (YYYY-MM)\n"
            "- `?search=` — free-text search across project names"
        ),
        manual_parameters=[
            openapi.Parameter("project_name", openapi.IN_QUERY, type=openapi.TYPE_STRING, required=False),
            openapi.Parameter("progress_month", openapi.IN_QUERY, type=openapi.TYPE_STRING, required=False),
            openapi.Parameter("search", openapi.IN_QUERY, type=openapi.TYPE_STRING, required=False),
            openapi.Parameter("page", openapi.IN_QUERY, type=openapi.TYPE_INTEGER, required=False),
            openapi.Parameter("page_size", openapi.IN_QUERY, type=openapi.TYPE_INTEGER, required=False),
        ],
        responses={200: openapi.Response("OK", _CP_RESPONSE_SCHEMA)},
        tags=["Construction Progress"],
    )
    def list(self, request, *args, **kwargs):
        """Return all progress records (paginated, filterable). Cached for 5 min."""
        project_filter = request.query_params.get("project_name")
        month_filter = request.query_params.get("progress_month")
        search_filter = request.query_params.get("search")
        page_param = request.query_params.get("page", "1")
        use_cache = not any([project_filter, month_filter, search_filter]) and page_param == "1"

        if use_cache:
            cached = cache.get(_CACHE_KEY_LIST)
            if cached is not None:
                return Response(cached)

        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = ConstructionProgressSerializer(page, many=True)
            paginated = self.get_paginated_response(serializer.data)
            payload = {
                "success": True,
                "message": "Construction progress records retrieved successfully",
                "data": paginated.data,
            }
            if use_cache:
                cache.set(_CACHE_KEY_LIST, payload, _CACHE_TIMEOUT)
            return Response(payload)

        serializer = ConstructionProgressSerializer(queryset, many=True)
        payload = {
            "success": True,
            "message": "Construction progress records retrieved successfully",
            "data": serializer.data,
        }
        if use_cache:
            cache.set(_CACHE_KEY_LIST, payload, _CACHE_TIMEOUT)
        return Response(payload)

    # -------------------------------------------------------------------------
    # RETRIEVE  GET /api/construction-progress/{id}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get Construction Progress Record by ID",
        responses={200: openapi.Response("OK", _CP_RESPONSE_SCHEMA), 404: "Not found"},
        tags=["Construction Progress"],
    )
    def retrieve(self, request, *args, **kwargs):
        try:
            instance = ConstructionProgress.objects.get(pk=kwargs["pk"])
        except ConstructionProgress.DoesNotExist:
            return self._error("Construction progress record not found", http_status=status.HTTP_404_NOT_FOUND)
        return self._success(
            "Construction progress record retrieved successfully",
            ConstructionProgressSerializer(instance).data,
        )

    # -------------------------------------------------------------------------
    # UPDATE  PUT /api/construction-progress/{id}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Update Construction Progress Record",
        operation_description=(
            "Full or partial update of a monthly progress record. "
            "variance and performancePercentage are recalculated automatically."
        ),
        request_body=_CP_POST_SCHEMA,
        responses={
            200: openapi.Response("OK", _CP_RESPONSE_SCHEMA),
            400: "Validation error",
            404: "Not found",
        },
        tags=["Construction Progress"],
    )
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)

        try:
            instance = ConstructionProgress.objects.get(pk=kwargs["pk"])
        except ConstructionProgress.DoesNotExist:
            return self._error("Construction progress record not found", http_status=status.HTTP_404_NOT_FOUND)

        payload = {k: v for k, v in _normalize_payload(request.data).items() if k not in _READ_ONLY}

        serializer = ConstructionProgressSerializer(instance, data=payload, partial=partial)
        if not serializer.is_valid():
            return self._error("Invalid data provided", errors=serializer.errors)

        try:
            updated = serializer.save()
        except DjangoValidationError as exc:
            return self._error("Validation failed", errors=exc.message_dict)
        except Exception as exc:
            logger.error(f"ConstructionProgress update error: {exc}")
            return self._error(
                "Failed to update construction progress record",
                errors=str(exc),
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        self._invalidate_cache()
        return self._success(
            "Construction progress updated successfully",
            ConstructionProgressSerializer(updated).data,
        )

    def partial_update(self, request, *args, **kwargs):
        """PATCH — partial update, delegates to update() with partial=True."""
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    # -------------------------------------------------------------------------
    # DELETE  DELETE /api/construction-progress/{id}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Delete Construction Progress Record",
        responses={200: openapi.Response("OK"), 404: "Not found"},
        tags=["Construction Progress"],
    )
    def destroy(self, request, *args, **kwargs):
        try:
            instance = ConstructionProgress.objects.get(pk=kwargs["pk"])
        except ConstructionProgress.DoesNotExist:
            return self._error("Construction progress record not found", http_status=status.HTTP_404_NOT_FOUND)

        label = f"{instance.projectName} [{instance.progressMonth}]"
        instance.delete()
        self._invalidate_cache()
        return self._success(f"Construction progress record for '{label}' deleted successfully", {})

    # -------------------------------------------------------------------------
    # BY PROJECT  GET /api/construction-progress/project/{projectName}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get All Progress Records for a Project",
        operation_description=(
            "Retrieve all monthly progress records for a specific project "
            "(case-insensitive). Returns records ordered by progressMonth — "
            "ideal for planned vs actual charts and S-curve analytics."
        ),
        responses={200: openapi.Response("OK", _CP_RESPONSE_SCHEMA), 404: "Not found"},
        tags=["Construction Progress"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"project/(?P<projectName>[^/.]+)",
        url_name="by-project-name",
    )
    def get_by_project_name(self, request, projectName: str = None):
        """
        Retrieve all monthly progress records for a project (case-insensitive).
        Ordered by progressMonth — ready for chart/S-curve rendering.
        """
        if not projectName or not projectName.strip():
            return self._error("projectName is required.")

        records = ConstructionProgress.objects.filter(
            projectName__iexact=projectName.strip()
        ).order_by("progressMonth")

        if not records.exists():
            return self._error(
                f"No progress records found for project '{projectName}'",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        serializer = ConstructionProgressSerializer(records, many=True)
        return self._success(
            f"Construction progress records for '{projectName.strip()}' retrieved successfully",
            serializer.data,
        )

    # -------------------------------------------------------------------------
    # BY MONTH  GET /api/construction-progress/month/{progressMonth}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get All Progress Records for a Month",
        operation_description=(
            "Retrieve all project progress records for a specific month (YYYY-MM). "
            "Useful for monthly dashboard KPI cards and cross-project comparisons."
        ),
        responses={200: openapi.Response("OK", _CP_RESPONSE_SCHEMA), 400: "Invalid month format"},
        tags=["Construction Progress"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"month/(?P<progressMonth>[^/.]+)",
        url_name="by-month",
    )
    def get_by_month(self, request, progressMonth: str = None):
        """
        Retrieve all project progress records for a given month (YYYY-MM).
        Ideal for monthly KPI dashboard cards and cross-project comparisons.
        """
        import re as _re
        if not progressMonth or not _re.match(r"^\d{4}-(0[1-9]|1[0-2])$", progressMonth.strip()):
            return self._error(
                "progressMonth must be in YYYY-MM format (e.g. '2026-05').",
                http_status=status.HTTP_400_BAD_REQUEST,
            )

        records = ConstructionProgress.objects.filter(
            progressMonth=progressMonth.strip()
        ).order_by("projectName")

        serializer = ConstructionProgressSerializer(records, many=True)
        return self._success(
            f"Construction progress records for month '{progressMonth.strip()}' retrieved successfully",
            serializer.data,
        )
