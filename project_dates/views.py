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
  GET    /api/project-dates/project/{projectName}/        -> both SCL + CONTRACTOR + BG lists
  GET    /api/project-dates/project/{projectName}/bg-status/  -> BG Status lists + summary
  POST   /api/project-dates/project/{projectName}/bg-status/  -> create BG entry
  PATCH  /api/project-dates/bg-status/{id}/             -> partial update BG entry
  PUT    /api/project-dates/bg-status/{id}/             -> full update BG entry
  DELETE /api/project-dates/bg-status/{id}/             -> delete BG entry

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
from django.db.models import Prefetch
from django_filters.rest_framework import DjangoFilterBackend
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from projects.models import Project
from services.billing_update_notifications import (
    BillingAction,
    BillingModule,
    schedule_billing_update_notification,
    schedule_billing_update_notification_for_instance,
)

from .bg_serializers import (
    BGStatusCreateSerializer,
    BGStatusSerializer,
    BGStatusUpdateSerializer,
)
from .bg_status import BG_STATUSES, bg_status_payload
from .export import project_dates_csv_response, project_dates_rows
from .filters import ProjectDatesFilter
from .models import BGStatus, ProjectDates
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

_BG_ENTRY_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    properties={
        "id": openapi.Schema(type=openapi.TYPE_INTEGER, example=1),
        "bg_type": openapi.Schema(type=openapi.TYPE_STRING, enum=["CONTRACTOR", "SCL"]),
        "bg_name": openapi.Schema(type=openapi.TYPE_STRING, example="Performance BG"),
        "due_date": openapi.Schema(
            type=openapi.TYPE_STRING,
            format="date",
            nullable=True,
            example="2026-06-15",
        ),
        "updated_date": openapi.Schema(
            type=openapi.TYPE_STRING,
            format="date",
            nullable=True,
            example="2026-06-14",
        ),
        "status": openapi.Schema(type=openapi.TYPE_STRING, enum=BG_STATUSES),
        "remarks": openapi.Schema(type=openapi.TYPE_STRING, example=""),
    },
)

_BG_SUMMARY_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    properties={
        "total_bg": openapi.Schema(type=openapi.TYPE_INTEGER, example=3),
        "updated": openapi.Schema(type=openapi.TYPE_INTEGER, example=1),
        "yet_to_update": openapi.Schema(type=openapi.TYPE_INTEGER, example=1),
        "not_updated": openapi.Schema(type=openapi.TYPE_INTEGER, example=1),
        "compliance_percentage": openapi.Schema(type=openapi.TYPE_NUMBER, example=33.33),
    },
)

_BG_STATUS_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    properties={
        "contractor_bg": openapi.Schema(
            type=openapi.TYPE_ARRAY,
            items=_BG_ENTRY_SCHEMA,
        ),
        "scl_bg": openapi.Schema(
            type=openapi.TYPE_ARRAY,
            items=_BG_ENTRY_SCHEMA,
        ),
        "bg_summary": _BG_SUMMARY_SCHEMA,
    },
)

_BG_STATUS_CREATE_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    required=["bg_type"],
    properties={
        "bg_type": openapi.Schema(
            type=openapi.TYPE_STRING,
            enum=["CONTRACTOR", "SCL"],
            example="CONTRACTOR",
        ),
        "contractor_id": openapi.Schema(
            type=openapi.TYPE_INTEGER,
            description="Target contractor (preferred). Required when multiple contractors exist.",
            example=1,
        ),
        "contractor_name": openapi.Schema(
            type=openapi.TYPE_STRING,
            description="Deprecated — use contractor_id.",
            example="ABC Infra",
        ),
        "bg_name": openapi.Schema(
            type=openapi.TYPE_STRING,
            example="Performance BG",
            description="Optional display name",
        ),
        "due_date": openapi.Schema(
            type=openapi.TYPE_STRING,
            format="date",
            nullable=True,
            example="2026-06-15",
            description="Optional bank guarantee due date",
        ),
        "updated_date": openapi.Schema(
            type=openapi.TYPE_STRING,
            format="date",
            nullable=True,
            example="2026-06-14",
        ),
        "remarks": openapi.Schema(type=openapi.TYPE_STRING, example="Updated successfully"),
    },
)

_BG_STATUS_UPDATE_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    properties={
        "bg_name": openapi.Schema(type=openapi.TYPE_STRING, example="Performance BG"),
        "due_date": openapi.Schema(type=openapi.TYPE_STRING, format="date", example="2026-06-15"),
        "updated_date": openapi.Schema(
            type=openapi.TYPE_STRING,
            format="date",
            nullable=True,
            example="2026-06-16",
        ),
        "remarks": openapi.Schema(type=openapi.TYPE_STRING, example="Renewed"),
    },
)


_PD_POST_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    required=["project_name", "date_type", "project_start", "contract_finish", "forecast_finish"],
    properties={
        "project_name": openapi.Schema(type=openapi.TYPE_STRING, example="Thane Project"),
        "date_type": openapi.Schema(type=openapi.TYPE_STRING, enum=["SCL", "CONTRACTOR"], example="CONTRACTOR"),
        "contractor_id": openapi.Schema(
            type=openapi.TYPE_INTEGER,
            description="Required when date_type=CONTRACTOR (preferred). Omit for SCL.",
            example=1,
        ),
        "contractor_name": openapi.Schema(
            type=openapi.TYPE_STRING,
            description="Deprecated — use contractor_id.",
            example="ABC Infra",
        ),
        "project_start": openapi.Schema(type=openapi.TYPE_STRING, format="date", example="2024-06-01"),
        "contract_finish": openapi.Schema(type=openapi.TYPE_STRING, format="date", example="2026-06-01"),
        "forecast_finish": openapi.Schema(type=openapi.TYPE_STRING, format="date", example="2026-09-01"),
        "eot_date": openapi.Schema(
            type=openapi.TYPE_STRING,
            format="date",
            nullable=True,
            example="2026-12-01",
            description="Optional Extension of Time (EOT) date",
        ),
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
                "date_type": openapi.Schema(type=openapi.TYPE_STRING, example="CONTRACTOR"),
                "contractor_name": openapi.Schema(type=openapi.TYPE_STRING, example="ABC Infra", nullable=True),
                "project_start": openapi.Schema(type=openapi.TYPE_STRING, example="2024-06-01"),
                "contract_finish": openapi.Schema(type=openapi.TYPE_STRING, example="2026-06-01"),
                "forecast_finish": openapi.Schema(type=openapi.TYPE_STRING, example="2026-09-01"),
                "eot_date": openapi.Schema(type=openapi.TYPE_STRING, example="2026-12-01", nullable=True),
                "elapsed_duration": openapi.Schema(type=openapi.TYPE_INTEGER, description="Days from project_start to today", example=727),
                "remaining_duration": openapi.Schema(type=openapi.TYPE_INTEGER, description="Days from today to contract_finish", example=365),
                "forecast_finish_duration": openapi.Schema(type=openapi.TYPE_INTEGER, description="Days between forecast_finish and contract_finish", example=92),
                "eot_duration": openapi.Schema(type=openapi.TYPE_INTEGER, description="Days between eot_date and contract_finish", example=183),
                "delay_days": openapi.Schema(type=openapi.TYPE_INTEGER, description="Forecast delay: (forecast_finish - contract_finish).days", example=92),
                "eot_delay_days": openapi.Schema(type=openapi.TYPE_INTEGER, description="EOT extension: (eot_date - contract_finish).days", example=183),
                "current_delay": openapi.Schema(type=openapi.TYPE_INTEGER, description="Live overdue counter: (today - contract_finish).days. Positive = overdue.", example=15),
                "bg_status": _BG_STATUS_SCHEMA,
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
    Project Dates ViewSet — manages SCL and multiple Contractor schedule dates per project.

    One SCL record per project. Multiple CONTRACTOR records allowed (unique contractor_name).
    All duration fields are calculated fresh on every read — never stored.
    """

    queryset = ProjectDates.objects.select_related("project").prefetch_related(
        Prefetch(
            "bg_statuses",
            queryset=BGStatus.objects.order_by("id"),
        )
    )
    serializer_class = ProjectDatesSerializer
    pagination_class = ProjectDatesPagination
    lookup_value_regex = r"\d+"

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ProjectDatesFilter
    search_fields = ["project__name", "date_type"]
    ordering_fields = ["created_at", "updated_at", "project__name", "date_type", "contractor_name"]
    ordering = ["project__name", "date_type", "contractor_name"]

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
            "Create a new project dates record.\n\n"
            "**SCL:** one record per project (`contractor_name` omitted).\n"
            "**CONTRACTOR:** multiple records allowed — each POST creates a new contractor "
            "schedule identified by `contractor_name` (must be unique within the project).\n\n"
            "**Business rules:**\n"
            "- `project_start` ≤ `contract_finish`\n"
            "- `contract_finish` ≤ `eot_date` (when `eot_date` is provided)\n"
            "- `eot_date` is optional\n"
            "- BG Status is managed separately and is not required here\n"
            "- `contractor_name` required when `date_type=CONTRACTOR`\n\n"
            "**Calculated fields (auto-computed, not stored):**\n"
            "- `elapsed_duration`, `remaining_duration`, `forecast_finish_duration`, "
            "`eot_duration`, `delay_days`, `eot_delay_days`, `current_delay`"
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

        schedule_billing_update_notification_for_instance(
            request.user,
            instance,
            BillingModule.PROJECT_DATES,
            BillingAction.CREATE,
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

        if request.query_params.get("export", "").lower() == "csv":
            rows = project_dates_rows(queryset)
            return project_dates_csv_response(rows)

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

        schedule_billing_update_notification_for_instance(
            request.user,
            updated,
            BillingModule.PROJECT_DATES,
            BillingAction.UPDATE,
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

        label = f"{instance.project.name} [{instance.date_type}"
        if instance.contractor_name:
            label += f" — {instance.contractor_name}"
        label += "]"
        schedule_billing_update_notification(
            request.user,
            instance.project,
            BillingModule.PROJECT_DATES,
            BillingAction.DELETE,
        )
        instance.delete()
        return self._success(f"Project dates record for '{label}' deleted successfully", {})

    # -------------------------------------------------------------------------
    # BG STATUS  GET/POST /api/project-dates/project/{projectName}/bg-status/
    #            PUT/PATCH/DELETE /api/project-dates/bg-status/{id}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        method="get",
        operation_summary="Get BG Status for a Project",
        operation_description=(
            "Returns all Contractor and SCL bank guarantee entries for a project "
            "with dynamically calculated status and compliance summary."
        ),
        responses={200: _BG_STATUS_SCHEMA, 404: "Project not found"},
        tags=["Project Dates"],
    )
    @swagger_auto_schema(
        method="post",
        operation_summary="Create BG Status Entry",
        operation_description=(
            "Create a new bank guarantee entry for a specific schedule row.\n\n"
            "For CONTRACTOR BG entries, pass `contractor_name` when the project has "
            "multiple contractor schedules. BG entries are scoped to the selected "
            "contractor and never mixed across contractors."
        ),
        request_body=_BG_STATUS_CREATE_SCHEMA,
        responses={201: _BG_ENTRY_SCHEMA, 400: "Validation error", 404: "Project not found"},
        tags=["Project Dates"],
    )
    @action(
        detail=False,
        methods=["get", "post"],
        url_path=r"project/(?P<projectName>[^/.]+)/bg-status",
        url_name="project-bg-status",
    )
    def project_bg_status(self, request, projectName: str = None):
        """GET all BG entries or POST a new BG entry for a project."""
        if not projectName or not projectName.strip():
            return self._error("projectName is required.")

        try:
            project = Project.objects.get(name__iexact=projectName.strip())
        except Project.DoesNotExist:
            return self._error(
                f"No project found with name '{projectName.strip()}'",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        if request.method == "GET":
            contractor_name = (request.query_params.get("contractor_name") or "").strip()
            contractor_id = request.query_params.get("contractor_id")
            if contractor_id or contractor_name:
                from .bg_status import get_project_date_for_bg, bg_status_for_project_date

                try:
                    parsed_id = int(contractor_id) if contractor_id else None
                except (TypeError, ValueError):
                    return self._error("contractor_id must be a valid integer.")

                project_date = get_project_date_for_bg(
                    project,
                    ProjectDates.DATE_TYPE_CONTRACTOR,
                    contractor_name or None,
                    contractor_id=parsed_id,
                )
                if project_date is None:
                    label = contractor_id or contractor_name
                    return self._error(
                        f"No contractor schedule found for '{label}' on this project.",
                        http_status=status.HTTP_404_NOT_FOUND,
                    )
                label = (
                    project_date.contractor_name
                    or (project_date.contractor.contractor_name if project_date.contractor_id else "")
                )
                payload = bg_status_for_project_date(project_date)
                return self._success(
                    f"BG Status for contractor '{label}' retrieved successfully",
                    payload,
                )

            return self._success(
                f"BG Status for '{project.name}' retrieved successfully",
                bg_status_payload(project),
            )

        serializer = BGStatusCreateSerializer(
            data=request.data,
            context={"project": project},
        )
        if not serializer.is_valid():
            return self._error("Validation failed", errors=serializer.errors)

        try:
            instance = serializer.save()
        except Exception as exc:
            logger.error(f"BGStatus create error: {exc}")
            return self._error(
                "Failed to create BG Status entry",
                errors=str(exc),
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        schedule_billing_update_notification(
            request.user,
            project,
            BillingModule.BG_STATUS,
            BillingAction.CREATE,
        )

        return self._success(
            f"BG Status entry for '{project.name}' created successfully",
            BGStatusSerializer(instance).data,
            http_status=status.HTTP_201_CREATED,
        )

    @swagger_auto_schema(
        method="patch",
        operation_summary="Update BG Status Entry (PUT/PATCH)",
        operation_description="Partially update a single bank guarantee entry by ID.",
        request_body=_BG_STATUS_UPDATE_SCHEMA,
        responses={200: _BG_ENTRY_SCHEMA, 400: "Validation error", 404: "Not found"},
        tags=["Project Dates"],
    )
    @swagger_auto_schema(
        method="delete",
        operation_summary="Delete BG Status Entry",
        operation_description="Delete a single bank guarantee entry by ID.",
        responses={200: "Deleted", 404: "Not found"},
        tags=["Project Dates"],
    )
    @action(
        detail=False,
        methods=["put", "patch", "delete"],
        url_path=r"bg-status/(?P<bgId>\d+)",
        url_name="bg-status-by-id",
    )
    def bg_status_by_id(self, request, bgId: str = None):
        """PUT, PATCH, or DELETE a single BG entry."""
        try:
            instance = BGStatus.objects.select_related(
                "project_date",
                "project_date__project",
            ).get(pk=bgId)
        except BGStatus.DoesNotExist:
            return self._error(
                "BG Status entry not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        if request.method == "DELETE":
            label = instance.bg_name
            schedule_billing_update_notification(
                request.user,
                instance.project_date.project,
                BillingModule.BG_STATUS,
                BillingAction.DELETE,
            )
            instance.delete()
            return self._success(f"BG Status entry '{label}' deleted successfully", {})

        serializer = BGStatusUpdateSerializer(
            instance,
            data=request.data,
            partial=request.method == "PATCH",
        )
        if not serializer.is_valid():
            return self._error("Validation failed", errors=serializer.errors)

        try:
            updated = serializer.save()
        except Exception as exc:
            logger.error(f"BGStatus update error: {exc}")
            return self._error(
                "Failed to update BG Status entry",
                errors=str(exc),
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        schedule_billing_update_notification(
            request.user,
            updated.project_date.project,
            BillingModule.BG_STATUS,
            BillingAction.UPDATE,
        )

        return self._success(
            "BG Status entry updated successfully",
            BGStatusSerializer(updated).data,
        )

    # -------------------------------------------------------------------------
    # BY PROJECT  GET /api/project-dates/project/{projectName}/
    # Returns both SCL and CONTRACTOR records together in one response
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get SCL and Contractor Dates for a Project",
        operation_description=(
            "Retrieve SCL and all contractor schedule records for a project "
            "(case-insensitive name match).\n\n"
            "Returns `contractors` as an array (one entry per contractor). "
            "`contractor` is kept for backward compatibility and points to the "
            "first contractor when present."
        ),
        manual_parameters=[
            openapi.Parameter(
                "contractor_name",
                openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                required=False,
                description="Optional: filter BG status GET on bg-status endpoint only",
            ),
        ],
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
                                "contractors": openapi.Schema(
                                    type=openapi.TYPE_ARRAY,
                                    items=openapi.Schema(type=openapi.TYPE_OBJECT),
                                    description="All contractor schedules with scoped bg_status",
                                ),
                                "contractor": openapi.Schema(
                                    type=openapi.TYPE_OBJECT,
                                    nullable=True,
                                    description="Deprecated — first contractor for backward compatibility",
                                ),
                                "contractor_bg": openapi.Schema(
                                    type=openapi.TYPE_ARRAY,
                                    items=_BG_ENTRY_SCHEMA,
                                ),
                                "scl_bg": openapi.Schema(
                                    type=openapi.TYPE_ARRAY,
                                    items=_BG_ENTRY_SCHEMA,
                                ),
                                "bg_summary": _BG_SUMMARY_SCHEMA,
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
        Return SCL and all contractor schedule records for a project.

        Response includes:
          - scl: single SCL record or null
          - contractors: array of contractor schedules (each with scoped bg_status)
          - contractor: first contractor (backward compatibility)
        """
        if not projectName or not projectName.strip():
            return self._error("projectName is required.")

        project_name = projectName.strip()

        records = (
            ProjectDates.objects
            .select_related("project")
            .prefetch_related(
                Prefetch(
                    "bg_statuses",
                    queryset=BGStatus.objects.order_by("id"),
                )
            )
            .filter(project__name__iexact=project_name)
            .order_by("date_type", "contractor_name")
        )

        if not records.exists():
            return self._error(
                f"No project dates records found for project '{project_name}'",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        scl_record = None
        contractor_records = []
        for record in records:
            if record.date_type == ProjectDates.DATE_TYPE_SCL:
                scl_record = record
            else:
                contractor_records.append(record)

        project = (scl_record or contractor_records[0]).project
        actual_name = project.name
        bg_payload = bg_status_payload(project)

        contractors_data = [
            ProjectDatesSerializer(record).data for record in contractor_records
        ]

        payload = {
            "project_name": actual_name,
            "scl": ProjectDatesSerializer(scl_record).data if scl_record else None,
            "contractors": contractors_data,
            "contractor": contractors_data[0] if contractors_data else None,
            "contractor_bg": bg_payload["contractor_bg"],
            "scl_bg": bg_payload["scl_bg"],
            "bg_summary": bg_payload["bg_summary"],
        }

        if request.query_params.get("export", "").lower() == "csv":
            rows = project_dates_rows(records)
            return project_dates_csv_response(
                rows,
                filename=f"project_dates_{actual_name.replace(' ', '_')}.csv",
            )

        return self._success(
            f"Project dates for '{actual_name}' retrieved successfully",
            payload,
        )
