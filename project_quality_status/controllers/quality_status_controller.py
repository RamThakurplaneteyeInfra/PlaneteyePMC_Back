"""
Project Quality Status Controller (ViewSet).

Handles all CRUD operations for ProjectQualityStatus records.
Uses DRF ModelViewSet with a uniform {success, message, data} response envelope.

Standard endpoints (via router):
  POST   /api/project-quality-status/                          -> create
  GET    /api/project-quality-status/                          -> list (paginated, filterable)
  GET    /api/project-quality-status/{id}/                     -> retrieve by ID
  PUT    /api/project-quality-status/{id}/                     -> full update
  PATCH  /api/project-quality-status/{id}/                     -> partial update
  DELETE /api/project-quality-status/{id}/                     -> destroy

Custom filter endpoint (via @action):
  GET    /api/project-quality-status/project/{projectName}/    -> lookup by project name

Auto-calculated fields (never send, always returned):
  - variance              = totalTestsConducted - totalTestsPassed
  - performancePercentage = (totalTestsPassed / totalTestsConducted) * 100

Runtime-computed fields (not stored, derived on read):
  - qualityStatus  (excellent / good / average / poor)
  - failedTests    (alias for variance)

Scalable for future additions:
  - Category-wise tests
  - Monthly quality tracking
  - Failed test history
  - QA/QC reports and compliance analytics
  - Quality trends and forecasting
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

from ..models.project_quality_status import ProjectQualityStatus
from .quality_status_serializer import ProjectQualityStatusSerializer

logger = logging.getLogger(__name__)

# Cache settings
_CACHE_KEY_LIST = "project_quality_status_list"
_CACHE_TIMEOUT = 300  # 5 minutes

# Mapping of snake_case keys the frontend may send → camelCase keys the serializer expects
_SNAKE_TO_CAMEL = {
    "project_name": "projectName",
    "total_tests_conducted": "totalTestsConducted",
    "total_tests_passed": "totalTestsPassed",
}


def _normalize_payload(data: dict) -> dict:
    """
    Accept both snake_case and camelCase field names from the frontend.
    Converts any snake_case keys to the camelCase names the serializer expects.
    """
    return {_SNAKE_TO_CAMEL.get(k, k): v for k, v in data.items()}


# =============================================================================
# Pagination
# =============================================================================

class QualityStatusPagination(PageNumberPagination):
    """Standard pagination for quality status records (20/page, configurable)."""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


# =============================================================================
# Swagger schema helpers
# =============================================================================

_PQS_POST_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    required=["projectName", "totalTestsConducted", "totalTestsPassed"],
    properties={
        "projectName": openapi.Schema(
            type=openapi.TYPE_STRING,
            description="Unique project name",
            example="Atlas Tower",
        ),
        "totalTestsConducted": openapi.Schema(
            type=openapi.TYPE_INTEGER,
            description="Total quality tests conducted (>= 0)",
            example=200,
        ),
        "totalTestsPassed": openapi.Schema(
            type=openapi.TYPE_INTEGER,
            description=(
                "Total quality tests passed "
                "(>= 0, cannot exceed totalTestsConducted)"
            ),
            example=185,
        ),
    },
)

_PQS_RESPONSE_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    properties={
        "success": openapi.Schema(type=openapi.TYPE_BOOLEAN, example=True),
        "message": openapi.Schema(
            type=openapi.TYPE_STRING,
            example="Project quality status created successfully",
        ),
        "data": openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                "id": openapi.Schema(type=openapi.TYPE_INTEGER, example=1),
                "projectName": openapi.Schema(
                    type=openapi.TYPE_STRING, example="Atlas Tower"
                ),
                "totalTestsConducted": openapi.Schema(
                    type=openapi.TYPE_INTEGER, example=200
                ),
                "totalTestsPassed": openapi.Schema(
                    type=openapi.TYPE_INTEGER, example=185
                ),
                "variance": openapi.Schema(
                    type=openapi.TYPE_INTEGER,
                    description="Auto-calculated: totalTestsConducted - totalTestsPassed",
                    example=15,
                ),
                "performancePercentage": openapi.Schema(
                    type=openapi.TYPE_NUMBER,
                    description="Auto-calculated: (totalTestsPassed / totalTestsConducted) * 100",
                    example=92.5,
                ),
                "qualityStatus": openapi.Schema(
                    type=openapi.TYPE_STRING,
                    description="excellent | good | average | poor",
                    example="good",
                ),
                "failedTests": openapi.Schema(
                    type=openapi.TYPE_INTEGER,
                    description="Alias for variance — number of failed/pending tests",
                    example=15,
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

class ProjectQualityStatusViewSet(viewsets.ModelViewSet):
    """
    Project Quality Status ViewSet.

    One record per project — tracks cumulative quality testing KPIs
    for dashboard performance gauges and project health monitoring.

    All calculated fields are auto-computed by the model on every save.
    Clients only need to send:
      projectName, totalTestsConducted, totalTestsPassed.

    Quality status thresholds (performancePercentage):
      >= 95%  → 'excellent'
      >= 80%  → 'good'
      >= 60%  → 'average'
      < 60%   → 'poor'
    """

    queryset = ProjectQualityStatus.objects.all()
    serializer_class = ProjectQualityStatusSerializer
    permission_classes = [AllowAny]
    pagination_class = QualityStatusPagination

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
        qs = ProjectQualityStatus.objects.only(
            "id",
            "projectName",
            "totalTestsConducted",
            "totalTestsPassed",
            "variance",
            "performancePercentage",
            "created_at",
            "updated_at",
        )

        project_name = self.request.query_params.get("project_name")
        if project_name:
            qs = qs.filter(projectName__icontains=project_name.strip())

        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(projectName__icontains=search.strip())

        return qs

    # -------------------------------------------------------------------------
    # Response helpers
    # -------------------------------------------------------------------------

    def _invalidate_cache(self):
        """Invalidate the list cache whenever data changes."""
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
    # CREATE  POST /api/project-quality-status/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Create Project Quality Status Record",
        operation_description=(
            "Create a new quality status record for a project.\n\n"
            "**Auto-calculated fields (do not send):**\n"
            "- `variance` = totalTestsConducted − totalTestsPassed\n"
            "- `performancePercentage` = (totalTestsPassed / totalTestsConducted) × 100\n\n"
            "**Constraint:** totalTestsPassed cannot exceed totalTestsConducted."
        ),
        request_body=_PQS_POST_SCHEMA,
        responses={
            201: openapi.Response("Created", _PQS_RESPONSE_SCHEMA),
            400: "Validation error",
        },
        tags=["Project Quality Status"],
    )
    def create(self, request, *args, **kwargs):
        """
        Create or update a project quality status record (upsert by projectName).

        If a record already exists for the given projectName it is updated
        in-place rather than returning a 500 uniqueness error.
        Auto-calculates variance and performancePercentage.
        """
        # Normalize snake_case → camelCase first, then read projectName
        _READ_ONLY = {"variance", "performancePercentage", "qualityStatus", "failedTests", "id", "created_at", "updated_at"}
        payload = {k: v for k, v in _normalize_payload(request.data).items() if k not in _READ_ONLY}

        project_name = str(payload.get("projectName", "")).strip()

        # Upsert: if a record already exists for this project, update it.
        existing = None
        if project_name:
            try:
                existing = ProjectQualityStatus.objects.get(
                    projectName__iexact=project_name
                )
            except ProjectQualityStatus.DoesNotExist:
                pass

        if existing is not None:
            serializer = ProjectQualityStatusSerializer(
                existing, data=payload, partial=False
            )
        else:
            serializer = ProjectQualityStatusSerializer(data=payload)

        if not serializer.is_valid():
            return self._error("Invalid data provided", errors=serializer.errors)

        try:
            instance = serializer.save()
        except DjangoValidationError as exc:
            return self._error("Validation failed", errors=exc.message_dict)
        except Exception as exc:
            logger.error(f"ProjectQualityStatus create error: {exc}")
            return self._error(
                "Failed to create quality status record",
                errors=str(exc),
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        self._invalidate_cache()

        http_status = status.HTTP_200_OK if existing else status.HTTP_201_CREATED
        message = (
            "Project quality status updated successfully"
            if existing
            else "Project quality status created successfully"
        )

        return self._success(
            message,
            ProjectQualityStatusSerializer(instance).data,
            http_status=http_status,
        )

    # -------------------------------------------------------------------------
    # LIST  GET /api/project-quality-status/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get All Project Quality Status Records",
        operation_description=(
            "Retrieve all quality status records.\n\n"
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
        responses={200: openapi.Response("OK", _PQS_RESPONSE_SCHEMA)},
        tags=["Project Quality Status"],
    )
    def list(self, request, *args, **kwargs):
        """
        Return all quality status records (paginated, filterable).
        Results are cached for 5 minutes; cache is invalidated on any write.
        """
        project_filter = request.query_params.get("project_name")
        search_filter = request.query_params.get("search")
        page_param = request.query_params.get("page", "1")
        use_cache = not any([project_filter, search_filter]) and page_param == "1"

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

    # -------------------------------------------------------------------------
    # RETRIEVE  GET /api/project-quality-status/{id}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get Project Quality Status Record by ID",
        responses={
            200: openapi.Response("OK", _PQS_RESPONSE_SCHEMA),
            404: "Not found",
        },
        tags=["Project Quality Status"],
    )
    def retrieve(self, request, *args, **kwargs):
        """Retrieve a single quality status record by its primary key."""
        try:
            instance = ProjectQualityStatus.objects.get(pk=kwargs["pk"])
        except ProjectQualityStatus.DoesNotExist:
            return self._error(
                "Project quality status record not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        return self._success(
            "Project quality status record retrieved successfully",
            ProjectQualityStatusSerializer(instance).data,
        )

    # -------------------------------------------------------------------------
    # UPDATE  PUT /api/project-quality-status/{id}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Update Project Quality Status Record",
        operation_description=(
            "Full or partial update of a quality status record. "
            "variance and performancePercentage are recalculated automatically."
        ),
        request_body=_PQS_POST_SCHEMA,
        responses={
            200: openapi.Response("OK", _PQS_RESPONSE_SCHEMA),
            400: "Validation error",
            404: "Not found",
        },
        tags=["Project Quality Status"],
    )
    def update(self, request, *args, **kwargs):
        """
        Full update (PUT) of a quality status record.
        All calculated fields are recomputed after update.
        """
        partial = kwargs.pop("partial", False)

        try:
            instance = ProjectQualityStatus.objects.get(pk=kwargs["pk"])
        except ProjectQualityStatus.DoesNotExist:
            return self._error(
                "Project quality status record not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        _READ_ONLY = {"variance", "performancePercentage", "qualityStatus", "failedTests", "id", "created_at", "updated_at"}
        payload = {k: v for k, v in _normalize_payload(request.data).items() if k not in _READ_ONLY}

        serializer = ProjectQualityStatusSerializer(
            instance, data=payload, partial=partial
        )

        if not serializer.is_valid():
            return self._error("Invalid data provided", errors=serializer.errors)

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
        """PATCH — partial update, delegates to update() with partial=True."""
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    # -------------------------------------------------------------------------
    # DELETE  DELETE /api/project-quality-status/{id}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Delete Project Quality Status Record",
        responses={
            200: openapi.Response("OK"),
            404: "Not found",
        },
        tags=["Project Quality Status"],
    )
    def destroy(self, request, *args, **kwargs):
        """Delete a quality status record by its primary key."""
        try:
            instance = ProjectQualityStatus.objects.get(pk=kwargs["pk"])
        except ProjectQualityStatus.DoesNotExist:
            return self._error(
                "Project quality status record not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        project_name = instance.projectName
        instance.delete()
        self._invalidate_cache()

        return self._success(
            f"Project quality status record for '{project_name}' deleted successfully",
            {},
        )

    # -------------------------------------------------------------------------
    # CUSTOM ACTION  GET /api/project-quality-status/project/{projectName}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get Project Quality Status by Project Name",
        operation_description=(
            "Retrieve a quality status record using the exact project name "
            "(case-insensitive). Returns all KPI fields including "
            "qualityStatus and failedTests — ready for dashboard "
            "gauge meters and quality cards."
        ),
        responses={
            200: openapi.Response("OK", _PQS_RESPONSE_SCHEMA),
            404: "Not found",
        },
        tags=["Project Quality Status"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"project/(?P<projectName>[^/.]+)",
        url_name="by-project-name",
    )
    def get_by_project_name(self, request, projectName: str = None):
        """
        Retrieve a quality status record by exact project name (case-insensitive).
        Ideal for dashboard KPI card and gauge integration.
        """
        if not projectName or not projectName.strip():
            return self._error("projectName is required.")

        try:
            instance = ProjectQualityStatus.objects.get(
                projectName__iexact=projectName.strip()
            )
        except ProjectQualityStatus.DoesNotExist:
            return self._error(
                f"No quality status record found for project '{projectName}'",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        return self._success(
            "Project quality status record retrieved successfully",
            ProjectQualityStatusSerializer(instance).data,
        )
