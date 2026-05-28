"""
Drawing Controller (ViewSet).

Handles all CRUD operations for Drawing records.
Uses DRF ModelViewSet for clean, DRY implementation with custom response format.

Endpoints (registered via router in drawing_routes.py):
  POST   /api/drawings/                          -> create_drawing
  GET    /api/drawings/                          -> get_all_drawings
  GET    /api/drawings/{id}/                     -> retrieve single record
  PUT    /api/drawings/{id}/                     -> update_drawing (full update)
  PATCH  /api/drawings/{id}/                     -> partial update
  DELETE /api/drawings/{id}/                     -> delete_drawing
  GET    /api/drawings/project/{projectName}/    -> get_drawing_by_project_name
"""

from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from ..models.drawing import Drawing
from .drawing_serializer import DrawingSerializer


# =============================================================================
# Payload normalisation
# =============================================================================

# Maps legacy / incorrect frontend field names → canonical backend field names.
# This lets the frontend send either the old names or the correct names and
# always get a valid response instead of a 400.
_FIELD_ALIASES: dict[str, str] = {
    # Legacy field names the frontend was sending
    "project_name": "projectName",
    "submitted_drawings": "totalSubmitted",
    "approved_drawings": "totalApproved",
}

# Fields the frontend should NOT send (backend calculates them automatically).
# Strip them silently so they never cause unexpected validation errors.
_STRIP_FIELDS: set[str] = {"variance", "approval_percentage", "approvalPercentage"}


def _normalise_payload(data: dict) -> dict:
    """
    Return a new dict with:
      1. Legacy field names renamed to their canonical equivalents.
      2. Auto-calculated / read-only fields removed.
      3. Numeric string values for totalSubmitted / totalApproved coerced to int.

    The original ``data`` dict is never mutated.
    """
    normalised: dict = {}

    for key, value in data.items():
        # Rename legacy keys
        canonical_key = _FIELD_ALIASES.get(key, key)

        # Drop fields the backend calculates automatically
        if canonical_key in _STRIP_FIELDS:
            continue

        normalised[canonical_key] = value

    # Coerce numeric strings → int for the two count fields
    for field in ("totalSubmitted", "totalApproved"):
        if field in normalised:
            try:
                normalised[field] = int(normalised[field])
            except (TypeError, ValueError):
                pass  # Let the serializer produce the proper validation error

    return normalised


def _flatten_errors(errors) -> dict:
    """
    Convert DRF / Django validation error dicts into plain string values so
    the frontend never receives ``[object Object]`` in the error payload.

    Input example:
        {"totalApproved": ["totalApproved (10) cannot be greater than totalSubmitted (5)."]}
    Output:
        {"totalApproved": "totalApproved (10) cannot be greater than totalSubmitted (5)."}
    """
    flat: dict = {}
    if isinstance(errors, dict):
        for field, messages in errors.items():
            if isinstance(messages, list):
                flat[field] = " ".join(str(m) for m in messages)
            elif isinstance(messages, dict):
                # Nested dict — recurse one level
                flat[field] = _flatten_errors(messages)
            else:
                flat[field] = str(messages)
    elif isinstance(errors, list):
        return {"detail": " ".join(str(m) for m in errors)}
    else:
        return {"detail": str(errors)}
    return flat

# Cache key prefix for drawings list
_CACHE_KEY_LIST = "drawings_list"
_CACHE_TIMEOUT = 300  # 5 minutes


# =============================================================================
# Pagination
# =============================================================================

class DrawingPagination(PageNumberPagination):
    """Standard pagination for drawing records (20 per page, configurable)."""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


# =============================================================================
# Swagger schema helpers
# =============================================================================

_DRAWING_POST_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    required=["projectName", "totalSubmitted", "totalApproved"],
    properties={
        "projectName": openapi.Schema(
            type=openapi.TYPE_STRING,
            description="Unique project name",
            example="Atlas Tower",
        ),
        "totalSubmitted": openapi.Schema(
            type=openapi.TYPE_INTEGER,
            description="Total drawings submitted (≥ 0)",
            example=120,
        ),
        "totalApproved": openapi.Schema(
            type=openapi.TYPE_INTEGER,
            description="Total drawings approved (≥ 0, ≤ totalSubmitted)",
            example=95,
        ),
    },
)

_DRAWING_RESPONSE_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    properties={
        "success": openapi.Schema(type=openapi.TYPE_BOOLEAN, example=True),
        "message": openapi.Schema(
            type=openapi.TYPE_STRING, example="Drawing data created successfully"
        ),
        "data": openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                "id": openapi.Schema(type=openapi.TYPE_INTEGER, example=1),
                "projectName": openapi.Schema(
                    type=openapi.TYPE_STRING, example="Atlas Tower"
                ),
                "totalSubmitted": openapi.Schema(type=openapi.TYPE_INTEGER, example=120),
                "totalApproved": openapi.Schema(type=openapi.TYPE_INTEGER, example=95),
                "variance": openapi.Schema(type=openapi.TYPE_INTEGER, example=25),
                "approvalPercentage": openapi.Schema(
                    type=openapi.TYPE_NUMBER, example=79.17
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

class DrawingViewSet(viewsets.ModelViewSet):
    """
    Drawing Management ViewSet.

    Provides full CRUD for Drawing records plus a project-name lookup action.
    All calculated fields (variance, approvalPercentage) are auto-computed
    by the model on every save — clients never need to send them.

    Scalable for future additions:
      - pending drawings
      - drawing revisions
      - discipline-wise drawings
      - monthly progress tracking
      - drawing status analytics
    """

    queryset = Drawing.objects.all()
    serializer_class = DrawingSerializer
    permission_classes = [AllowAny]
    pagination_class = DrawingPagination

    # -------------------------------------------------------------------------
    # Queryset optimisation
    # -------------------------------------------------------------------------

    def get_queryset(self):
        """
        Return optimised queryset.
        Supports optional ?project_name= filter for project-wise filtering.
        """
        qs = Drawing.objects.only(
            "id",
            "projectName",
            "totalSubmitted",
            "totalApproved",
            "variance",
            "approvalPercentage",
            "created_at",
            "updated_at",
        )

        # Optional project-wise filter via query param: ?project_name=Atlas
        project_name = self.request.query_params.get("project_name")
        if project_name:
            qs = qs.filter(projectName__icontains=project_name.strip())

        return qs

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _invalidate_list_cache(self):
        """Invalidate the cached list whenever data changes."""
        cache.delete(_CACHE_KEY_LIST)

    def _success_response(self, message: str, data, http_status=status.HTTP_200_OK):
        """Uniform success response wrapper used across all actions."""
        return Response(
            {"success": True, "message": message, "data": data},
            status=http_status,
        )

    def _error_response(self, message: str, errors=None, http_status=status.HTTP_400_BAD_REQUEST):
        """Uniform error response wrapper."""
        payload = {"success": False, "message": message}
        if errors is not None:
            payload["errors"] = errors
        return Response(payload, status=http_status)

    # -------------------------------------------------------------------------
    # CREATE  POST /api/drawings/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Create Drawing Record",
        operation_description=(
            "Create a new drawing record for a project. "
            "variance and approvalPercentage are auto-calculated."
        ),
        request_body=_DRAWING_POST_SCHEMA,
        responses={
            201: openapi.Response("Created", _DRAWING_RESPONSE_SCHEMA),
            400: "Validation error",
        },
        tags=["Drawings"],
    )
    def create(self, request, *args, **kwargs):
        """
        Create or update a drawing record (upsert by projectName).

        If a record already exists for the given projectName it is updated
        in-place rather than returning a 400 uniqueness error.  This matches
        the expected dashboard behaviour where the frontend always POSTs the
        latest counts for a project.

        Accepts both canonical field names (projectName, totalSubmitted,
        totalApproved) and the legacy names the frontend may send
        (project_name, submitted_drawings, approved_drawings).

        variance and approvalPercentage are auto-calculated by the model —
        the client must NOT send them; they are silently stripped if present.
        """
        payload = _normalise_payload(request.data)

        project_name = payload.get("projectName", "").strip()

        # ------------------------------------------------------------------
        # Upsert: if a record already exists for this project, update it.
        # ------------------------------------------------------------------
        existing = None
        if project_name:
            try:
                existing = Drawing.objects.get(projectName__iexact=project_name)
            except Drawing.DoesNotExist:
                pass

        if existing is not None:
            # Partial=False so the full record is replaced with the new values
            serializer = DrawingSerializer(existing, data=payload, partial=False)
        else:
            serializer = DrawingSerializer(data=payload)

        if not serializer.is_valid():
            return self._error_response(
                "Invalid data provided",
                errors=_flatten_errors(serializer.errors),
            )

        try:
            instance = serializer.save()
        except DjangoValidationError as exc:
            return self._error_response(
                "Validation failed", errors=_flatten_errors(exc.message_dict)
            )

        self._invalidate_list_cache()

        http_status = status.HTTP_200_OK if existing else status.HTTP_201_CREATED
        message = (
            "Drawing data updated successfully"
            if existing
            else "Drawing data created successfully"
        )

        return self._success_response(
            message,
            DrawingSerializer(instance).data,
            http_status=http_status,
        )

    # -------------------------------------------------------------------------
    # LIST  GET /api/drawings/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get All Drawing Records",
        operation_description=(
            "Retrieve all drawing records. "
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
        responses={200: openapi.Response("OK", _DRAWING_RESPONSE_SCHEMA)},
        tags=["Drawings"],
    )
    def list(self, request, *args, **kwargs):
        """
        Return all drawing records (paginated).
        Results are cached for 5 minutes; cache is invalidated on any write.
        """
        # Only cache un-filtered, first-page requests
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
            serializer = DrawingSerializer(page, many=True)
            paginated_response = self.get_paginated_response(serializer.data)
            payload = {
                "success": True,
                "message": "Drawing records retrieved successfully",
                "data": paginated_response.data,
            }
            if use_cache:
                cache.set(_CACHE_KEY_LIST, payload, _CACHE_TIMEOUT)
            return Response(payload)

        serializer = DrawingSerializer(queryset, many=True)
        payload = {
            "success": True,
            "message": "Drawing records retrieved successfully",
            "data": serializer.data,
        }
        if use_cache:
            cache.set(_CACHE_KEY_LIST, payload, _CACHE_TIMEOUT)
        return Response(payload)

    # -------------------------------------------------------------------------
    # RETRIEVE  GET /api/drawings/{id}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get Drawing Record by ID",
        responses={
            200: openapi.Response("OK", _DRAWING_RESPONSE_SCHEMA),
            404: "Not found",
        },
        tags=["Drawings"],
    )
    def retrieve(self, request, *args, **kwargs):
        """Retrieve a single drawing record by its primary key."""
        try:
            instance = Drawing.objects.get(pk=kwargs["pk"])
        except Drawing.DoesNotExist:
            return self._error_response(
                "Drawing not found", http_status=status.HTTP_404_NOT_FOUND
            )

        return self._success_response(
            "Drawing record retrieved successfully",
            DrawingSerializer(instance).data,
        )

    # -------------------------------------------------------------------------
    # UPDATE  PUT /api/drawings/{id}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Update Drawing Record",
        operation_description=(
            "Full or partial update of a drawing record. "
            "variance and approvalPercentage are recalculated automatically."
        ),
        request_body=_DRAWING_POST_SCHEMA,
        responses={
            200: openapi.Response("OK", _DRAWING_RESPONSE_SCHEMA),
            400: "Validation error",
            404: "Not found",
        },
        tags=["Drawings"],
    )
    def update(self, request, *args, **kwargs):
        """
        Full update (PUT) or partial update (PATCH) of a drawing record.

        Accepts both canonical and legacy field names (same normalisation as
        create). variance and approvalPercentage are recalculated automatically.
        """
        partial = kwargs.pop("partial", False)

        try:
            instance = Drawing.objects.get(pk=kwargs["pk"])
        except Drawing.DoesNotExist:
            return self._error_response(
                "Drawing not found", http_status=status.HTTP_404_NOT_FOUND
            )

        payload = _normalise_payload(request.data)

        serializer = DrawingSerializer(instance, data=payload, partial=partial)

        if not serializer.is_valid():
            return self._error_response(
                "Invalid data provided",
                errors=_flatten_errors(serializer.errors),
            )

        try:
            updated_instance = serializer.save()
        except DjangoValidationError as exc:
            return self._error_response(
                "Validation failed", errors=_flatten_errors(exc.message_dict)
            )

        self._invalidate_list_cache()

        return self._success_response(
            "Drawing data updated successfully",
            DrawingSerializer(updated_instance).data,
        )

    def partial_update(self, request, *args, **kwargs):
        """PATCH — partial update, delegates to update() with partial=True."""
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    # -------------------------------------------------------------------------
    # DELETE  DELETE /api/drawings/{id}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Delete Drawing Record",
        responses={
            200: openapi.Response("OK"),
            404: "Not found",
        },
        tags=["Drawings"],
    )
    def destroy(self, request, *args, **kwargs):
        """Delete a drawing record by its primary key."""
        try:
            instance = Drawing.objects.get(pk=kwargs["pk"])
        except Drawing.DoesNotExist:
            return self._error_response(
                "Drawing not found", http_status=status.HTTP_404_NOT_FOUND
            )

        project_name = instance.projectName
        instance.delete()
        self._invalidate_list_cache()

        return self._success_response(
            f"Drawing record for '{project_name}' deleted successfully",
            {},
        )

    # -------------------------------------------------------------------------
    # CUSTOM ACTION  GET /api/drawings/project/{projectName}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get Drawing Record by Project Name",
        operation_description="Retrieve a drawing record using the exact project name.",
        responses={
            200: openapi.Response("OK", _DRAWING_RESPONSE_SCHEMA),
            404: "Not found",
        },
        tags=["Drawings"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"project/(?P<projectName>[^/.]+)",
        url_name="by-project-name",
    )
    def get_by_project_name(self, request, projectName: str = None):
        """
        Retrieve a drawing record by exact project name (case-insensitive).
        Useful for dashboard KPI lookups where the project name is known.
        """
        if not projectName or not projectName.strip():
            return self._error_response("projectName is required.")

        try:
            instance = Drawing.objects.get(
                projectName__iexact=projectName.strip()
            )
        except Drawing.DoesNotExist:
            return self._error_response(
                f"No drawing record found for project '{projectName}'",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        return self._success_response(
            "Drawing record retrieved successfully",
            DrawingSerializer(instance).data,
        )
