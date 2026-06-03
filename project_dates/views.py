"""
Project Dates ViewSet.

Handles all CRUD operations for ProjectDates records.
Uses DRF ModelViewSet with a uniform {success, message, data} response envelope.

Endpoints:
  POST   /api/project-dates/                              -> create
  GET    /api/project-dates/                              -> list (paginated, filterable)
  GET    /api/project-dates/{id}/                         -> retrieve by ID
  PUT    /api/project-dates/{id}/                         -> full update
  PATCH  /api/project-dates/{id}/                         -> partial update
  DELETE /api/project-dates/{id}/                         -> destroy

Custom endpoint:
  GET    /api/project-dates/project/{projectName}/        -> both SCL + CONTRACTOR for a project

Filtering:
  ?project_name=Thane Project   (partial, case-insensitive)
  ?date_type=SCL
  ?date_type=CONTRACTOR

Ordering:
  ?ordering=created_at
  ?ordering=-updated_at
"""

import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from django_filters.rest_framework import DjangoFilterBackend
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .filters import ProjectDatesFilter
from .models import ProjectDates
from .serializers import ProjectDatesSerializer

logger = logging.getLogger(__name__)


# =============================================================================
# Pagination
# =============================================================================

class ProjectDatesPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


# =============================================================================
# Swagger schema helpers
# =============================================================================

_PD_POST_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    required=["project_name", "date_type", "project_start", "contract_finish", "forecast_finish", "eot_date"],
    properties={
        "project_name": openapi.Schema(type=openapi.TYPE_STRING, example="Thane Project"),
        "date_type": openapi.Schema(type=openapi.TYPE_STRING, enum=["SCL", "CONTRACTOR"], example="SCL"),
        "project_start": openapi.Schema(type=openapi.TYPE_STRING, format="date", example="2024-06-01"),
        "contract_finish": openapi.Schema(type=openapi.TYPE_STRING, format="date", example="2026-06-01"),
        "forecast_finish": openapi.Schema(type=openapi.TYPE_STRING, format="date", example="2026-09-01"),
        "eot_date": openapi.Schema(type=openapi.TYPE_STRING, format="date", example="2026-12-01"),
    },
)

_PD_RESPONSE_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    properties={
        "success": openapi.Schema(type=openapi.TYPE_BOOLEAN, example=True),
        "message": openapi.Schema(type=openapi.TYPE_STRING),
        "data": openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                "id": openapi.Schema(type=openapi.TYPE_INTEGER, example=1),
                "project_name": openapi.Schema(type=openapi.TYPE_STRING, example="Thane Project"),
                "date_type": openapi.Schema(type=openapi.TYPE_STRING, example="SCL"),
                "project_start": openapi.Schema(type=openapi.TYPE_STRING, example="2024-06-01"),
                "contract_finish": openapi.Schema(type=openapi.TYPE_STRING, example="2026-06-01"),
                "forecast_finish": openapi.Schema(type=openapi.TYPE_STRING, example="2026-09-01"),
                "eot_date": openapi.Schema(type=openapi.TYPE_STRING, example="2026-12-01"),
                "elapsed_duration": openapi.Schema(type=openapi.TYPE_INTEGER, description="Days from project_start to today", example=727),
                "remaining_duration": openapi.Schema(type=openapi.TYPE_INTEGER, description="Days from today to contract_finish", example=365),
                "forecast_finish_duration": openapi.Schema(type=openapi.TYPE_INTEGER, description="Days between forecast_finish and contract_finish", example=92),
                "eot_duration": openapi.Schema(type=openapi.TYPE_INTEGER, description="Days between eot_date and contract_finish", example=183),
                "delay_days": openapi.Schema(type=openapi.TYPE_INTEGER, description="Forecast delay: (forecast_finish - contract_finish).days", example=92),
                "eot_delay_days": openapi.Schema(type=openapi.TYPE_INTEGER, description="EOT extension: (eot_date - contract_finish).days", example=183),
                "current_delay": openapi.Schema(type=openapi.TYPE_INTEGER, description="Live overdue counter: (today - contract_finish).days. Positive = overdue.", example=15),
                "created_at": openapi.Schema(type=openapi.TYPE_STRING, example="2026-05-01T10:00:00Z"),
                "updated_at": openapi.Schema(type=openapi.TYPE_STRING, example="2026-05-28T12:00:00Z"),
            },
        ),
    },
)


# =============================================================================
# ViewSet
# =============================================================================

class ProjectDatesViewSet(viewsets.ModelViewSet):
    """
    Project Dates ViewSet — manages SCL and Contractor schedule dates per project.

    One SCL record and one CONTRACTOR record per project.
    All duration fields are calculated fresh on every read — never stored.

    Duration formulas:
      elapsed_duration         = (today - project_start).days
      remaining_duration       = (contract_finish - today).days
      forecast_finish_duration = (forecast_finish - contract_finish).days
      eot_duration             = (eot_date - contract_finish).days
    """

    queryset = ProjectDates.objects.select_related("project").all()
    serializer_class = ProjectDatesSerializer
    pagination_class = ProjectDatesPagination

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ProjectDatesFilter
    search_fields = ["project__name", "date_type"]
    ordering_fields = ["created_at", "updated_at", "project__name", "date_type"]
    ordering = ["project__name", "date_type"]

    # -------------------------------------------------------------------------
    # Response helpers
    # -------------------------------------------------------------------------

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
    # CREATE  POST /api/project-dates/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Create Project Dates Record (SCL or Contractor)",
        operation_description=(
            "Create a new project dates record for SCL or CONTRACTOR.\n\n"
            "**One record per project per date_type** — duplicates are rejected.\n\n"
            "**Business rules:**\n"
            "- `project_start` ≤ `contract_finish`\n"
            "- `contract_finish` ≤ `eot_date`\n"
            "- `forecast_finish` may be before or after `contract_finish` (early or delayed forecast)\n\n"
            "**Calculated fields (auto-computed, not stored):**\n"
            "- `elapsed_duration` = (today − project_start).days\n"
            "- `remaining_duration` = (contract_finish − today).days\n"
            "- `forecast_finish_duration` = (forecast_finish − contract_finish).days\n"
            "- `eot_duration` = (eot_date − contract_finish).days"
        ),
        request_body=_PD_POST_SCHEMA,
        responses={
            201: openapi.Response("Created", _PD_RESPONSE_SCHEMA),
            400: "Validation error",
        },
        tags=["Project Dates"],
    )
    def create(self, request, *args, **kwargs):
        serializer = ProjectDatesSerializer(data=request.data)
        if not serializer.is_valid():
            return self._error("Validation failed", errors=serializer.errors)

        try:
            instance = serializer.save()
        except DjangoValidationError as exc:
            return self._error("Validation failed", errors=exc.message_dict)
        except Exception as exc:
            logger.error(f"ProjectDates create error: {exc}")
            return self._error(
                "Failed to save project dates record",
                errors=str(exc),
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return self._success(
            "Project dates saved successfully",
            ProjectDatesSerializer(instance).data,
            http_status=status.HTTP_201_CREATED,
        )

    # -------------------------------------------------------------------------
    # LIST  GET /api/project-dates/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get All Project Dates Records",
        operation_description=(
            "Retrieve all project dates records.\n\n"
            "**Supports filtering:**\n"
            "- `?project_name=` — partial, case-insensitive project name\n"
            "- `?date_type=SCL` or `?date_type=CONTRACTOR`\n\n"
            "**Supports ordering:**\n"
            "- `?ordering=created_at`, `?ordering=-updated_at`"
        ),
        manual_parameters=[
            openapi.Parameter("project_name", openapi.IN_QUERY, type=openapi.TYPE_STRING, required=False),
            openapi.Parameter("date_type", openapi.IN_QUERY, type=openapi.TYPE_STRING, required=False, enum=["SCL", "CONTRACTOR"]),
            openapi.Parameter("ordering", openapi.IN_QUERY, type=openapi.TYPE_STRING, required=False),
            openapi.Parameter("page", openapi.IN_QUERY, type=openapi.TYPE_INTEGER, required=False),
            openapi.Parameter("page_size", openapi.IN_QUERY, type=openapi.TYPE_INTEGER, required=False),
        ],
        responses={200: openapi.Response("OK", _PD_RESPONSE_SCHEMA)},
        tags=["Project Dates"],
    )
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = ProjectDatesSerializer(page, many=True)
            paginated = self.get_paginated_response(serializer.data)
            return Response({
                "success": True,
                "message": "Project dates records retrieved successfully",
                "data": paginated.data,
            })

        serializer = ProjectDatesSerializer(queryset, many=True)
        return Response({
            "success": True,
            "message": "Project dates records retrieved successfully",
            "data": serializer.data,
        })

    # -------------------------------------------------------------------------
    # RETRIEVE  GET /api/project-dates/{id}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get Project Dates Record by ID",
        responses={200: openapi.Response("OK", _PD_RESPONSE_SCHEMA), 404: "Not found"},
        tags=["Project Dates"],
    )
    def retrieve(self, request, *args, **kwargs):
        try:
            instance = ProjectDates.objects.select_related("project").get(pk=kwargs["pk"])
        except ProjectDates.DoesNotExist:
            return self._error("Project dates record not found", http_status=status.HTTP_404_NOT_FOUND)

        return self._success(
            "Project dates record retrieved successfully",
            ProjectDatesSerializer(instance).data,
        )

    # -------------------------------------------------------------------------
    # UPDATE  PUT /api/project-dates/{id}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Update Project Dates Record",
        operation_description="Full or partial update. All duration fields are recalculated automatically.",
        request_body=_PD_POST_SCHEMA,
        responses={
            200: openapi.Response("OK", _PD_RESPONSE_SCHEMA),
            400: "Validation error",
            404: "Not found",
        },
        tags=["Project Dates"],
    )
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)

        try:
            instance = ProjectDates.objects.select_related("project").get(pk=kwargs["pk"])
        except ProjectDates.DoesNotExist:
            return self._error("Project dates record not found", http_status=status.HTTP_404_NOT_FOUND)

        serializer = ProjectDatesSerializer(instance, data=request.data, partial=partial)
        if not serializer.is_valid():
            return self._error("Validation failed", errors=serializer.errors)

        try:
            updated = serializer.save()
        except DjangoValidationError as exc:
            return self._error("Validation failed", errors=exc.message_dict)
        except Exception as exc:
            logger.error(f"ProjectDates update error: {exc}")
            return self._error(
                "Failed to update project dates record",
                errors=str(exc),
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return self._success(
            "Project dates updated successfully",
            ProjectDatesSerializer(updated).data,
        )

    def partial_update(self, request, *args, **kwargs):
        """PATCH — partial update."""
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    # -------------------------------------------------------------------------
    # DELETE  DELETE /api/project-dates/{id}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Delete Project Dates Record",
        responses={200: openapi.Response("OK"), 404: "Not found"},
        tags=["Project Dates"],
    )
    def destroy(self, request, *args, **kwargs):
        try:
            instance = ProjectDates.objects.select_related("project").get(pk=kwargs["pk"])
        except ProjectDates.DoesNotExist:
            return self._error("Project dates record not found", http_status=status.HTTP_404_NOT_FOUND)

        label = f"{instance.project.name} [{instance.date_type}]"
        instance.delete()
        return self._success(f"Project dates record for '{label}' deleted successfully", {})

    # -------------------------------------------------------------------------
    # BY PROJECT  GET /api/project-dates/project/{projectName}/
    # Returns both SCL and CONTRACTOR records together in one response
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get Both SCL and Contractor Dates for a Project",
        operation_description=(
            "Retrieve both SCL and CONTRACTOR date records for a specific project "
            "(case-insensitive name match) in a single response.\n\n"
            "Returns `null` for whichever record does not exist yet."
        ),
        responses={
            200: openapi.Response(
                "OK",
                openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        "success": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                        "message": openapi.Schema(type=openapi.TYPE_STRING),
                        "data": openapi.Schema(
                            type=openapi.TYPE_OBJECT,
                            properties={
                                "project_name": openapi.Schema(type=openapi.TYPE_STRING, example="Thane Project"),
                                "scl": openapi.Schema(type=openapi.TYPE_OBJECT, nullable=True),
                                "contractor": openapi.Schema(type=openapi.TYPE_OBJECT, nullable=True),
                            },
                        ),
                    },
                ),
            ),
            404: "Project not found",
        },
        tags=["Project Dates"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"project/(?P<projectName>[^/.]+)",
        url_name="by-project-name",
    )
    def get_by_project_name(self, request, projectName: str = None):
        """
        Return both SCL and CONTRACTOR records for a project in one response.

        Example response:
        {
          "success": true,
          "message": "...",
          "data": {
            "project_name": "Thane Project",
            "scl": { ...SCL record with all duration fields... },
            "contractor": { ...CONTRACTOR record with all duration fields... }
          }
        }

        Either scl or contractor will be null if that record hasn't been created yet.
        """
        if not projectName or not projectName.strip():
            return self._error("projectName is required.")

        project_name = projectName.strip()

        records = (
            ProjectDates.objects
            .select_related("project")
            .filter(project__name__iexact=project_name)
        )

        if not records.exists():
            return self._error(
                f"No project dates records found for project '{project_name}'",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        # Build a dict keyed by date_type
        by_type = {r.date_type: r for r in records}

        scl_record = by_type.get(ProjectDates.DATE_TYPE_SCL)
        contractor_record = by_type.get(ProjectDates.DATE_TYPE_CONTRACTOR)

        # Use the actual project name from whichever record exists
        actual_name = (scl_record or contractor_record).project.name

        return self._success(
            f"Project dates for '{actual_name}' retrieved successfully",
            {
                "project_name": actual_name,
                "scl": ProjectDatesSerializer(scl_record).data if scl_record else None,
                "contractor": ProjectDatesSerializer(contractor_record).data if contractor_record else None,
            },
        )
