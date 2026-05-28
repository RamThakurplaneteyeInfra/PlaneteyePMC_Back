"""
Correspondence Controller (ViewSet).

Handles all CRUD operations for Correspondence records.
Uses DRF ModelViewSet for a clean, DRY implementation with a uniform
{success, message, data} response envelope on every endpoint.

Endpoints (registered via router in correspondence_routes.py):
  POST   /api/correspondence/                          -> create
  GET    /api/correspondence/                          -> list (paginated, filterable)
  GET    /api/correspondence/{id}/                     -> retrieve by ID
  PUT    /api/correspondence/{id}/                     -> full update
  PATCH  /api/correspondence/{id}/                     -> partial update
  DELETE /api/correspondence/{id}/                     -> destroy
  GET    /api/correspondence/project/{projectName}/    -> lookup by project name

Auto-calculated fields returned on every response (never sent by client):
  - pendingCorrespondence  = correspondenceReceived - correspondenceDelivered
  - deliveryPercentage     = (correspondenceDelivered / correspondenceReceived) * 100

Scalable for future additions:
  - monthly correspondence tracking
  - inward / outward correspondence history
  - document categories
  - priority levels
  - overdue correspondence tracking
  - project-wise delivery analytics
  - charts and KPI cards
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

from ..models.correspondence import Correspondence
from .correspondence_serializer import CorrespondenceSerializer

logger = logging.getLogger(__name__)

# Cache settings
_CACHE_KEY_LIST = "correspondence_list"
_CACHE_TIMEOUT = 300  # 5 minutes


# =============================================================================
# Pagination
# =============================================================================

class CorrespondencePagination(PageNumberPagination):
    """Standard pagination for correspondence records (20 per page, configurable)."""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


# =============================================================================
# Swagger schema helpers
# =============================================================================

_CORRESPONDENCE_POST_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    required=["projectName"],
    properties={
        "projectName": openapi.Schema(
            type=openapi.TYPE_STRING,
            description="Unique project name",
            example="Atlas Tower",
        ),
        "correspondenceReceived": openapi.Schema(
            type=openapi.TYPE_INTEGER,
            description="Total correspondence items received (≥ 0)",
            example=150,
        ),
        "correspondenceDelivered": openapi.Schema(
            type=openapi.TYPE_INTEGER,
            description=(
                "Total correspondence items delivered "
                "(≥ 0, must not exceed correspondenceReceived)"
            ),
            example=120,
        ),
    },
)

_CORRESPONDENCE_RESPONSE_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    properties={
        "success": openapi.Schema(type=openapi.TYPE_BOOLEAN, example=True),
        "message": openapi.Schema(
            type=openapi.TYPE_STRING,
            example="Correspondence record created successfully",
        ),
        "data": openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                "id": openapi.Schema(type=openapi.TYPE_INTEGER, example=1),
                "projectName": openapi.Schema(
                    type=openapi.TYPE_STRING, example="Atlas Tower"
                ),
                "correspondenceReceived": openapi.Schema(
                    type=openapi.TYPE_INTEGER, example=150
                ),
                "correspondenceDelivered": openapi.Schema(
                    type=openapi.TYPE_INTEGER, example=120
                ),
                "pendingCorrespondence": openapi.Schema(
                    type=openapi.TYPE_INTEGER,
                    description="Auto-calculated: received - delivered",
                    example=30,
                ),
                "deliveryPercentage": openapi.Schema(
                    type=openapi.TYPE_NUMBER,
                    description="Auto-calculated: (delivered / received) * 100",
                    example=80.0,
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

class CorrespondenceViewSet(viewsets.ModelViewSet):
    """
    Correspondence & Delivery Status ViewSet.

    Provides full CRUD for Correspondence records plus a project-name lookup.
    All calculated fields (pendingCorrespondence, deliveryPercentage) are
    auto-computed by the model on every save — clients never need to send them.

    One record per project. Use PUT /api/correspondence/{id}/ to update
    as new correspondence data arrives.
    """

    queryset = Correspondence.objects.all()
    serializer_class = CorrespondenceSerializer
    permission_classes = [AllowAny]
    pagination_class = CorrespondencePagination

    # -------------------------------------------------------------------------
    # Queryset optimisation
    # -------------------------------------------------------------------------

    def get_queryset(self):
        """
        Return optimised queryset.
        Supports optional ?project_name= filter for project-wise filtering.
        """
        qs = Correspondence.objects.only(
            "id",
            "projectName",
            "correspondenceReceived",
            "correspondenceDelivered",
            "pendingCorrespondence",
            "deliveryPercentage",
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
    # CREATE  POST /api/correspondence/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Create Correspondence Record",
        operation_description=(
            "Create a new correspondence record for a project. "
            "pendingCorrespondence and deliveryPercentage are auto-calculated. "
            "correspondenceDelivered must not exceed correspondenceReceived."
        ),
        request_body=_CORRESPONDENCE_POST_SCHEMA,
        responses={
            201: openapi.Response("Created", _CORRESPONDENCE_RESPONSE_SCHEMA),
            400: "Validation error",
        },
        tags=["Correspondence"],
    )
    def create(self, request, *args, **kwargs):
        """
        Create or update a correspondence record (upsert by projectName).

        If a record already exists for the given projectName it is updated
        in-place rather than returning a 500 uniqueness error.
        Auto-calculates pendingCorrespondence and deliveryPercentage.
        """
        project_name = str(request.data.get("projectName", "")).strip()

        # Strip read-only / auto-calculated fields the frontend should not send
        _READ_ONLY = {"pendingCorrespondence", "deliveryPercentage", "id", "created_at", "updated_at"}
        payload = {k: v for k, v in request.data.items() if k not in _READ_ONLY}

        # Upsert: if a record already exists for this project, update it.
        existing = None
        if project_name:
            try:
                existing = Correspondence.objects.get(
                    projectName__iexact=project_name
                )
            except Correspondence.DoesNotExist:
                pass

        if existing is not None:
            serializer = CorrespondenceSerializer(
                existing, data=payload, partial=False
            )
        else:
            serializer = CorrespondenceSerializer(data=payload)

        if not serializer.is_valid():
            return self._error("Invalid data provided", errors=serializer.errors)

        try:
            instance = serializer.save()
        except DjangoValidationError as exc:
            return self._error("Validation failed", errors=exc.message_dict)
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
            else "Correspondence record created successfully"
        )

        return self._success(
            message,
            CorrespondenceSerializer(instance).data,
            http_status=http_status,
        )

    # -------------------------------------------------------------------------
    # LIST  GET /api/correspondence/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get All Correspondence Records",
        operation_description=(
            "Retrieve all correspondence records. "
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
        responses={200: openapi.Response("OK", _CORRESPONDENCE_RESPONSE_SCHEMA)},
        tags=["Correspondence"],
    )
    def list(self, request, *args, **kwargs):
        """
        Return all correspondence records (paginated).
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

    # -------------------------------------------------------------------------
    # RETRIEVE  GET /api/correspondence/{id}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get Correspondence Record by ID",
        responses={
            200: openapi.Response("OK", _CORRESPONDENCE_RESPONSE_SCHEMA),
            404: "Not found",
        },
        tags=["Correspondence"],
    )
    def retrieve(self, request, *args, **kwargs):
        """Retrieve a single correspondence record by its primary key."""
        try:
            instance = Correspondence.objects.get(pk=kwargs["pk"])
        except Correspondence.DoesNotExist:
            return self._error(
                "Correspondence record not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        return self._success(
            "Correspondence record retrieved successfully",
            CorrespondenceSerializer(instance).data,
        )

    # -------------------------------------------------------------------------
    # UPDATE  PUT /api/correspondence/{id}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Update Correspondence Record",
        operation_description=(
            "Full or partial update of a correspondence record. "
            "pendingCorrespondence and deliveryPercentage are recalculated automatically."
        ),
        request_body=_CORRESPONDENCE_POST_SCHEMA,
        responses={
            200: openapi.Response("OK", _CORRESPONDENCE_RESPONSE_SCHEMA),
            400: "Validation error",
            404: "Not found",
        },
        tags=["Correspondence"],
    )
    def update(self, request, *args, **kwargs):
        """
        Full update (PUT) of a correspondence record.
        Recalculates pendingCorrespondence and deliveryPercentage after update.
        """
        partial = kwargs.pop("partial", False)

        try:
            instance = Correspondence.objects.get(pk=kwargs["pk"])
        except Correspondence.DoesNotExist:
            return self._error(
                "Correspondence record not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        _READ_ONLY = {"pendingCorrespondence", "deliveryPercentage", "id", "created_at", "updated_at"}
        payload = {k: v for k, v in request.data.items() if k not in _READ_ONLY}

        serializer = CorrespondenceSerializer(
            instance, data=payload, partial=partial
        )

        if not serializer.is_valid():
            return self._error("Invalid data provided", errors=serializer.errors)

        try:
            updated = serializer.save()
        except DjangoValidationError as exc:
            return self._error("Validation failed", errors=exc.message_dict)
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
        """PATCH — partial update, delegates to update() with partial=True."""
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    # -------------------------------------------------------------------------
    # DELETE  DELETE /api/correspondence/{id}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Delete Correspondence Record",
        responses={
            200: openapi.Response("OK"),
            404: "Not found",
        },
        tags=["Correspondence"],
    )
    def destroy(self, request, *args, **kwargs):
        """Delete a correspondence record by its primary key."""
        try:
            instance = Correspondence.objects.get(pk=kwargs["pk"])
        except Correspondence.DoesNotExist:
            return self._error(
                "Correspondence record not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        project_name = instance.projectName
        instance.delete()
        self._invalidate_list_cache()

        return self._success(
            f"Correspondence record for '{project_name}' deleted successfully",
            {},
        )

    # -------------------------------------------------------------------------
    # CUSTOM ACTION  GET /api/correspondence/project/{projectName}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get Correspondence Record by Project Name",
        operation_description=(
            "Retrieve a correspondence record using the exact project name "
            "(case-insensitive). Useful for dashboard KPI card lookups."
        ),
        responses={
            200: openapi.Response("OK", _CORRESPONDENCE_RESPONSE_SCHEMA),
            404: "Not found",
        },
        tags=["Correspondence"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"project/(?P<projectName>[^/.]+)",
        url_name="by-project-name",
    )
    def get_by_project_name(self, request, projectName: str = None):
        """
        Retrieve a correspondence record by exact project name (case-insensitive).
        Returns all KPI fields ready for dashboard card rendering.
        """
        if not projectName or not projectName.strip():
            return self._error("projectName is required.")

        try:
            instance = Correspondence.objects.get(
                projectName__iexact=projectName.strip()
            )
        except Correspondence.DoesNotExist:
            return self._error(
                f"No correspondence record found for project '{projectName}'",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        return self._success(
            "Correspondence record retrieved successfully",
            CorrespondenceSerializer(instance).data,
        )
