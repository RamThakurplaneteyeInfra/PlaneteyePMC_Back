"""
Monthly Project Equipment Controller (ViewSet).

Handles all CRUD operations for ProjectEquipment records.
Uses DRF ModelViewSet with a uniform {success, message, data} response envelope.

Endpoints (mounted at /api/ in backend/urls.py):
  POST   /api/project-equipment/                               -> create
  GET    /api/project-equipment/                               -> list
  GET    /api/project-equipment/{id}/                          -> retrieve
  PUT    /api/project-equipment/{id}/                          -> full update
  PATCH  /api/project-equipment/{id}/                          -> partial update
  DELETE /api/project-equipment/{id}/                          -> destroy

Custom filter endpoints (via @action):
  GET    /api/project-equipment/project/{projectName}/         -> by project
  GET    /api/project-equipment/month/{equipmentMonth}/        -> by month

Auto-calculated fields (never send, always returned):
  - variance              = actualEquipment - plannedEquipment
  - performancePercentage = (actualEquipment / plannedEquipment) * 100

Runtime-computed field (not stored):
  - equipmentStatus  (fully_deployed / near_target / shortfall / critical_shortfall)

Frontend payload (camelCase or snake_case both accepted):
  {
    "projectName":      "Thane Project",
    "equipmentMonth":   "2026-05",
    "plannedEquipment": 32,
    "actualEquipment":  28,
    "remarks":          "Equipment shortage due to maintenance"  // optional
  }
"""

import logging
import re

from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from ..models.project_equipment import ProjectEquipment
from .project_equipment_serializer import ProjectEquipmentSerializer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
_CACHE_KEY_LIST = "project_equipment_list"
_CACHE_TIMEOUT = 300  # 5 minutes

# ---------------------------------------------------------------------------
# snake_case → camelCase normalisation
# ---------------------------------------------------------------------------
_SNAKE_TO_CAMEL = {
    "project_name": "projectName",
    "equipment_month": "equipmentMonth",
    "planned_equipment": "plannedEquipment",
    "actual_equipment": "actualEquipment",
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
    "equipmentStatus",
    "created_at",
    "updated_at",
}

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


# =============================================================================
# Pagination
# =============================================================================

class ProjectEquipmentPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


# =============================================================================
# Swagger schema helpers
# =============================================================================

_PE_POST_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    required=["projectName", "equipmentMonth", "plannedEquipment", "actualEquipment"],
    properties={
        "projectName": openapi.Schema(
            type=openapi.TYPE_STRING,
            description="Project name",
            example="Thane Project",
        ),
        "equipmentMonth": openapi.Schema(
            type=openapi.TYPE_STRING,
            description="Month in YYYY-MM format",
            example="2026-05",
        ),
        "plannedEquipment": openapi.Schema(
            type=openapi.TYPE_INTEGER,
            description="Planned equipment count for the month (>= 0)",
            example=32,
        ),
        "actualEquipment": openapi.Schema(
            type=openapi.TYPE_INTEGER,
            description="Actual equipment deployed this month (>= 0)",
            example=28,
        ),
        "remarks": openapi.Schema(
            type=openapi.TYPE_STRING,
            description="Optional remarks",
            example="Equipment shortage due to maintenance",
        ),
    },
)

_PE_RESPONSE_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    properties={
        "success": openapi.Schema(type=openapi.TYPE_BOOLEAN, example=True),
        "message": openapi.Schema(type=openapi.TYPE_STRING),
        "data": openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                "id": openapi.Schema(type=openapi.TYPE_INTEGER, example=1),
                "projectName": openapi.Schema(type=openapi.TYPE_STRING, example="Thane Project"),
                "equipmentMonth": openapi.Schema(type=openapi.TYPE_STRING, example="2026-05"),
                "plannedEquipment": openapi.Schema(type=openapi.TYPE_INTEGER, example=32),
                "actualEquipment": openapi.Schema(type=openapi.TYPE_INTEGER, example=28),
                "variance": openapi.Schema(
                    type=openapi.TYPE_INTEGER,
                    description="Auto-calculated: actualEquipment - plannedEquipment",
                    example=-4,
                ),
                "performancePercentage": openapi.Schema(
                    type=openapi.TYPE_NUMBER,
                    description="Auto-calculated: (actualEquipment / plannedEquipment) * 100",
                    example=87.5,
                ),
                "equipmentStatus": openapi.Schema(
                    type=openapi.TYPE_STRING,
                    description="fully_deployed | near_target | shortfall | critical_shortfall",
                    example="near_target",
                ),
                "remarks": openapi.Schema(type=openapi.TYPE_STRING, example="Equipment shortage due to maintenance"),
                "created_at": openapi.Schema(type=openapi.TYPE_STRING, example="2026-05-01T10:00:00Z"),
                "updated_at": openapi.Schema(type=openapi.TYPE_STRING, example="2026-05-28T12:00:00Z"),
            },
        ),
    },
)


# =============================================================================
# ViewSet
# =============================================================================

class ProjectEquipmentViewSet(viewsets.ModelViewSet):
    """
    Monthly Project Equipment ViewSet.

    One record per project per month — tracks planned vs actual equipment
    deployment for dashboard charts, KPI cards, and variance analytics.

    All calculated fields are auto-computed by the model on every save.
    Clients only need to send:
      projectName, equipmentMonth, plannedEquipment, actualEquipment, remarks (optional).

    Equipment status thresholds (performancePercentage):
      >= 100% → 'fully_deployed'
      >= 80%  → 'near_target'
      >= 60%  → 'shortfall'
      < 60%   → 'critical_shortfall'
    """

    queryset = ProjectEquipment.objects.all()
    serializer_class = ProjectEquipmentSerializer
    pagination_class = ProjectEquipmentPagination

    # -------------------------------------------------------------------------
    # Queryset
    # -------------------------------------------------------------------------

    def get_queryset(self):
        """
        Filterable queryset.

        Supported query params:
          ?project_name=    — partial, case-insensitive project name filter
          ?equipment_month= — exact month filter (YYYY-MM)
          ?search=          — free-text search across projectName
        """
        qs = ProjectEquipment.objects.all()

        project_name = self.request.query_params.get("project_name")
        if project_name:
            qs = qs.filter(projectName__icontains=project_name.strip())

        equipment_month = self.request.query_params.get("equipment_month")
        if equipment_month:
            qs = qs.filter(equipmentMonth=equipment_month.strip())

        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(projectName__icontains=search.strip())

        return qs.order_by("projectName", "equipmentMonth")

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
    # CREATE  POST /api/project-equipment/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Create Monthly Project Equipment Record",
        operation_description=(
            "Create a new monthly equipment record for a project.\n\n"
            "**One record per project per month** — duplicate month entries are rejected.\n\n"
            "**Auto-calculated fields (do not send):**\n"
            "- `variance` = actualEquipment − plannedEquipment\n"
            "- `performancePercentage` = (actualEquipment / plannedEquipment) × 100\n\n"
            "**equipmentMonth** must be in `YYYY-MM` format."
        ),
        request_body=_PE_POST_SCHEMA,
        responses={
            201: openapi.Response("Created", _PE_RESPONSE_SCHEMA),
            400: "Validation error",
        },
        tags=["Project Equipment"],
    )
    def create(self, request, *args, **kwargs):
        """
        Create a new monthly project equipment record.

        Duplicate (projectName + equipmentMonth) entries are rejected with a
        clear error message directing the client to use PUT for updates.
        """
        payload = {k: v for k, v in _normalize_payload(request.data).items() if k not in _READ_ONLY}

        serializer = ProjectEquipmentSerializer(data=payload)
        if not serializer.is_valid():
            return self._error("Invalid data provided", errors=serializer.errors)

        try:
            instance = serializer.save()
        except DjangoValidationError as exc:
            return self._error("Validation failed", errors=exc.message_dict)
        except Exception as exc:
            logger.error(f"ProjectEquipment create error: {exc}")
            return self._error(
                "Failed to save project equipment record",
                errors=str(exc),
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        self._invalidate_cache()
        return self._success(
            "Project equipment data saved successfully",
            ProjectEquipmentSerializer(instance).data,
            http_status=status.HTTP_201_CREATED,
        )

    # -------------------------------------------------------------------------
    # LIST  GET /api/project-equipment/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get All Project Equipment Records",
        operation_description=(
            "Retrieve all monthly equipment records.\n\n"
            "**Supports filtering:**\n"
            "- `?project_name=` — partial, case-insensitive project name\n"
            "- `?equipment_month=` — exact month (YYYY-MM)\n"
            "- `?search=` — free-text search across project names"
        ),
        manual_parameters=[
            openapi.Parameter("project_name", openapi.IN_QUERY, type=openapi.TYPE_STRING, required=False,
                              description="Filter by project name (partial, case-insensitive)"),
            openapi.Parameter("equipment_month", openapi.IN_QUERY, type=openapi.TYPE_STRING, required=False,
                              description="Filter by month (YYYY-MM)"),
            openapi.Parameter("search", openapi.IN_QUERY, type=openapi.TYPE_STRING, required=False,
                              description="Free-text search across project names"),
            openapi.Parameter("page", openapi.IN_QUERY, type=openapi.TYPE_INTEGER, required=False),
            openapi.Parameter("page_size", openapi.IN_QUERY, type=openapi.TYPE_INTEGER, required=False),
        ],
        responses={200: openapi.Response("OK", _PE_RESPONSE_SCHEMA)},
        tags=["Project Equipment"],
    )
    def list(self, request, *args, **kwargs):
        """Return all equipment records (paginated, filterable). Cached for 5 min."""
        project_filter = request.query_params.get("project_name")
        month_filter = request.query_params.get("equipment_month")
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
            serializer = ProjectEquipmentSerializer(page, many=True)
            paginated = self.get_paginated_response(serializer.data)
            payload = {
                "success": True,
                "message": "Project equipment records retrieved successfully",
                "data": paginated.data,
            }
            if use_cache:
                cache.set(_CACHE_KEY_LIST, payload, _CACHE_TIMEOUT)
            return Response(payload)

        serializer = ProjectEquipmentSerializer(queryset, many=True)
        payload = {
            "success": True,
            "message": "Project equipment records retrieved successfully",
            "data": serializer.data,
        }
        if use_cache:
            cache.set(_CACHE_KEY_LIST, payload, _CACHE_TIMEOUT)
        return Response(payload)

    # -------------------------------------------------------------------------
    # RETRIEVE  GET /api/project-equipment/{id}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get Project Equipment Record by ID",
        responses={200: openapi.Response("OK", _PE_RESPONSE_SCHEMA), 404: "Not found"},
        tags=["Project Equipment"],
    )
    def retrieve(self, request, *args, **kwargs):
        try:
            instance = ProjectEquipment.objects.get(pk=kwargs["pk"])
        except ProjectEquipment.DoesNotExist:
            return self._error(
                "Project equipment record not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )
        return self._success(
            "Project equipment record retrieved successfully",
            ProjectEquipmentSerializer(instance).data,
        )

    # -------------------------------------------------------------------------
    # UPDATE  PUT /api/project-equipment/{id}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Update Project Equipment Record",
        operation_description=(
            "Full or partial update of a monthly equipment record. "
            "variance and performancePercentage are recalculated automatically."
        ),
        request_body=_PE_POST_SCHEMA,
        responses={
            200: openapi.Response("OK", _PE_RESPONSE_SCHEMA),
            400: "Validation error",
            404: "Not found",
        },
        tags=["Project Equipment"],
    )
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)

        try:
            instance = ProjectEquipment.objects.get(pk=kwargs["pk"])
        except ProjectEquipment.DoesNotExist:
            return self._error(
                "Project equipment record not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        payload = {k: v for k, v in _normalize_payload(request.data).items() if k not in _READ_ONLY}

        serializer = ProjectEquipmentSerializer(instance, data=payload, partial=partial)
        if not serializer.is_valid():
            return self._error("Invalid data provided", errors=serializer.errors)

        try:
            updated = serializer.save()
        except DjangoValidationError as exc:
            return self._error("Validation failed", errors=exc.message_dict)
        except Exception as exc:
            logger.error(f"ProjectEquipment update error: {exc}")
            return self._error(
                "Failed to update project equipment record",
                errors=str(exc),
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        self._invalidate_cache()
        return self._success(
            "Project equipment record updated successfully",
            ProjectEquipmentSerializer(updated).data,
        )

    def partial_update(self, request, *args, **kwargs):
        """PATCH — partial update, delegates to update() with partial=True."""
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    # -------------------------------------------------------------------------
    # DELETE  DELETE /api/project-equipment/{id}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Delete Project Equipment Record",
        responses={200: openapi.Response("OK"), 404: "Not found"},
        tags=["Project Equipment"],
    )
    def destroy(self, request, *args, **kwargs):
        try:
            instance = ProjectEquipment.objects.get(pk=kwargs["pk"])
        except ProjectEquipment.DoesNotExist:
            return self._error(
                "Project equipment record not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        label = f"{instance.projectName} [{instance.equipmentMonth}]"
        instance.delete()
        self._invalidate_cache()
        return self._success(
            f"Project equipment record for '{label}' deleted successfully",
            {},
        )

    # -------------------------------------------------------------------------
    # BY PROJECT  GET /api/project-equipment/project/{projectName}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get All Equipment Records for a Project",
        operation_description=(
            "Retrieve all monthly equipment records for a specific project "
            "(case-insensitive). Returns records ordered by equipmentMonth — "
            "ideal for planned vs actual bar charts and trend analytics."
        ),
        responses={200: openapi.Response("OK", _PE_RESPONSE_SCHEMA), 404: "Not found"},
        tags=["Project Equipment"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"project/(?P<projectName>[^/.]+)",
        url_name="by-project-name",
    )
    def get_by_project_name(self, request, projectName: str = None):
        """
        Retrieve all monthly equipment records for a project (case-insensitive).
        Ordered by equipmentMonth — ready for chart rendering.
        """
        if not projectName or not projectName.strip():
            return self._error("projectName is required.")

        records = ProjectEquipment.objects.filter(
            projectName__iexact=projectName.strip()
        ).order_by("equipmentMonth")

        if not records.exists():
            return self._error(
                f"No equipment records found for project '{projectName}'",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        serializer = ProjectEquipmentSerializer(records, many=True)
        return self._success(
            f"Project equipment records for '{projectName.strip()}' retrieved successfully",
            serializer.data,
        )

    # -------------------------------------------------------------------------
    # BY MONTH  GET /api/project-equipment/month/{equipmentMonth}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get All Equipment Records for a Month",
        operation_description=(
            "Retrieve all project equipment records for a specific month (YYYY-MM). "
            "Useful for monthly dashboard KPI cards and cross-project comparisons."
        ),
        responses={200: openapi.Response("OK", _PE_RESPONSE_SCHEMA), 400: "Invalid month format"},
        tags=["Project Equipment"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"month/(?P<equipmentMonth>[^/.]+)",
        url_name="by-month",
    )
    def get_by_month(self, request, equipmentMonth: str = None):
        """
        Retrieve all project equipment records for a given month (YYYY-MM).
        Ideal for monthly KPI dashboard cards and cross-project comparisons.
        """
        if not equipmentMonth or not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", equipmentMonth.strip()):
            return self._error(
                "equipmentMonth must be in YYYY-MM format (e.g. '2026-05').",
                http_status=status.HTTP_400_BAD_REQUEST,
            )

        records = ProjectEquipment.objects.filter(
            equipmentMonth=equipmentMonth.strip()
        ).order_by("projectName")

        serializer = ProjectEquipmentSerializer(records, many=True)
        return self._success(
            f"Project equipment records for month '{equipmentMonth.strip()}' retrieved successfully",
            serializer.data,
        )
