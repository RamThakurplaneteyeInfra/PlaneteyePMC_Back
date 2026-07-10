"""
Planned vs Actual ViewSet — SCL + multiple contractors.

  POST   /api/planned-vs-actual/                         (UPSERT)
  GET    /api/planned-vs-actual/
  GET    /api/planned-vs-actual/{id}/
  PATCH  /api/planned-vs-actual/{id}/
  DELETE /api/planned-vs-actual/{id}/
  GET    /api/planned-vs-actual/project/{projectName}/
  GET    /api/planned-vs-actual/project/{projectName}/type/{plannedType}/
  GET    /api/planned-vs-actual/project/{projectName}/trend/
  GET    /api/planned-vs-actual/dashboard/?month=&year=
  GET    /api/planned-vs-actual/pending/?month=&year=
  GET    /api/planned-vs-actual/?export=csv|excel|pdf
"""

from __future__ import annotations

import logging
from calendar import month_abbr
from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from accounts.permissions import IsAuthenticatedProjectRBAC
from accounts.rbac import (
    RBACDomain,
    extract_project_name_from_data,
    normalize_project_name,
    resolve_project,
)
from accounts.rbac_checks import (
    apply_project_rbac_to_queryset,
    enforce_instance_write,
    enforce_project_access_by_name,
    enforce_project_write_by_name,
)
from contractors.models import Contractor
from contractors.resolvers import contractor_payload
from projects.models import Project
from services.billing_update_notifications import (
    BillingAction,
    BillingModule,
    schedule_billing_update_notification_for_instance,
)

from ..models.planned_earned_value import PlannedEarnedValue
from .export import export_response, planned_vs_actual_rows
from .metrics import (
    contractor_summary_from_records,
    empty_summary,
    summary_to_api,
)
from .planned_earned_value_serializer import PlannedEarnedValueSerializer

logger = logging.getLogger(__name__)

TWO_PLACES = Decimal("0.01")
ZERO = Decimal("0")

_READ_ONLY_FIELDS = {
    "difference",
    "achievement_percentage",
    "collection_percentage",
    "variance_percentage",
    "variance_status",
    "id",
    "created_at",
    "updated_at",
    "created_by",
    "updated_by",
    "project",
    "contractor",
    "contractor_name",
}


def _pct(numerator: Decimal, denominator: Decimal) -> float:
    if denominator == 0:
        return 0.0
    return float(
        ((numerator / denominator) * Decimal("100")).quantize(
            TWO_PLACES, rounding=ROUND_HALF_UP
        )
    )


def _flatten_errors(errors) -> dict:
    flat = {}
    if isinstance(errors, dict):
        for field, messages in errors.items():
            if isinstance(messages, list):
                flat[field] = " ".join(str(m) for m in messages)
            elif isinstance(messages, dict):
                flat[field] = _flatten_errors(messages)
            else:
                flat[field] = str(messages)
    elif isinstance(errors, list):
        return {"detail": " ".join(str(m) for m in errors)}
    else:
        return {"detail": str(errors)}
    return flat


def _find_existing_record(
    project_name: str,
    planned_type: str,
    month: int | None,
    year: int | None,
    contractor_id: int | None = None,
    contractor_name: str | None = None,
):
    if not project_name or not planned_type or month is None or year is None:
        return None
    try:
        month = int(month)
        year = int(year)
    except (TypeError, ValueError):
        return None

    filters = {
        "project_name__iexact": project_name.strip(),
        "planned_type": planned_type,
        "month": month,
        "year": year,
    }
    if planned_type == PlannedEarnedValue.TYPE_CONTRACTOR:
        if contractor_id:
            filters["contractor_id"] = contractor_id
        else:
            name = (contractor_name or "").strip()
            if not name:
                return None
            filters["contractor_name__iexact"] = name

    return PlannedEarnedValue.objects.filter(**filters).first()


def _build_project_payload(project_name: str, records) -> dict:
    scl_record = None
    contractor_records = []
    for record in records:
        if record.planned_type == PlannedEarnedValue.TYPE_SCL:
            scl_record = record
        else:
            contractor_records.append(record)

    contractors_data = [
        {
            "id": record.id,
            "contractor_name": record.contractor_name,
            "contractor": contractor_payload(record.contractor),
            "planned_vs_actual": PlannedEarnedValueSerializer(record).data,
        }
        for record in contractor_records
    ]
    first = contractors_data[0]["planned_vs_actual"] if contractors_data else None

    return {
        "project_name": project_name,
        "scl": PlannedEarnedValueSerializer(scl_record).data if scl_record else None,
        "contractor_summary": summary_to_api(
            contractor_summary_from_records(contractor_records)
        ),
        "contractors": contractors_data,
        "contractor": first or {},
    }


class PlannedEarnedValuePagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


_POST_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    required=[
        "project_name",
        "planned_type",
        "month",
        "year",
        "planned_value",
        "actual_value",
        "collection",
    ],
    properties={
        "project_name": openapi.Schema(type=openapi.TYPE_STRING, example="Thane Project"),
        "planned_type": openapi.Schema(
            type=openapi.TYPE_STRING, enum=["SCL", "CONTRACTOR"], example="SCL"
        ),
        "contractor_id": openapi.Schema(type=openapi.TYPE_INTEGER, example=3),
        "month": openapi.Schema(type=openapi.TYPE_INTEGER, example=7),
        "year": openapi.Schema(type=openapi.TYPE_INTEGER, example=2026),
        "planned_value": openapi.Schema(type=openapi.TYPE_NUMBER, example=15000000),
        "actual_value": openapi.Schema(type=openapi.TYPE_NUMBER, example=14500000),
        "collection": openapi.Schema(type=openapi.TYPE_NUMBER, example=14000000),
        "reason_for_difference": openapi.Schema(type=openapi.TYPE_STRING),
        "remarks": openapi.Schema(type=openapi.TYPE_STRING),
    },
)


class PlannedEarnedValueViewSet(viewsets.ModelViewSet):
    """Monthly Planned vs Actual — SCL + multiple contractors."""

    queryset = PlannedEarnedValue.objects.select_related(
        "project",
        "contractor",
        "created_by",
        "updated_by",
    )
    serializer_class = PlannedEarnedValueSerializer
    pagination_class = PlannedEarnedValuePagination
    permission_classes = [IsAuthenticatedProjectRBAC]
    rbac_domain = RBACDomain.FINANCIAL
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = self.queryset.all()
        params = self.request.query_params

        project_name = params.get("project_name") or params.get("project")
        if project_name:
            qs = qs.filter(project_name__icontains=project_name.strip())

        planned_type = params.get("planned_type") or params.get("value_type")
        if planned_type:
            qs = qs.filter(planned_type=planned_type.strip().upper())

        contractor_id = params.get("contractor_id")
        if contractor_id:
            try:
                qs = qs.filter(contractor_id=int(contractor_id))
            except ValueError:
                pass

        year = params.get("year")
        if year:
            try:
                qs = qs.filter(year=int(year))
            except ValueError:
                pass

        month = params.get("month")
        if month:
            try:
                qs = qs.filter(month=int(month))
            except ValueError:
                pass

        variance_status = params.get("variance_status")
        if variance_status:
            qs = qs.filter(variance_status=variance_status.strip().upper())

        billing_se = params.get("billing_site_engineer")
        if billing_se:
            if str(billing_se).isdigit():
                qs = qs.filter(project__billing_site_engineer_id=int(billing_se))
            else:
                qs = qs.filter(
                    Q(project__billing_site_engineer__username__icontains=billing_se.strip())
                    | Q(project__billing_site_engineer__first_name__icontains=billing_se.strip())
                    | Q(project__billing_site_engineer__last_name__icontains=billing_se.strip())
                )

        team_leader = params.get("team_leader")
        if team_leader:
            if str(team_leader).isdigit():
                qs = qs.filter(project__team_lead_id=int(team_leader))
            else:
                qs = qs.filter(
                    Q(project__team_lead__username__icontains=team_leader.strip())
                    | Q(project__team_lead__first_name__icontains=team_leader.strip())
                    | Q(project__team_lead__last_name__icontains=team_leader.strip())
                )

        qs = qs.order_by(
            "project_name", "year", "month", "planned_type", "contractor_name"
        )
        return apply_project_rbac_to_queryset(qs, self.request, "project_name")

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

    def _clean_payload(self, data) -> dict:
        if hasattr(data, "items"):
            return {k: v for k, v in data.items() if k not in _READ_ONLY_FIELDS}
        return {}

    @swagger_auto_schema(
        operation_summary="Create or update Planned vs Actual (UPSERT)",
        request_body=_POST_SCHEMA,
        tags=["Planned vs Actual"],
    )
    def create(self, request, *args, **kwargs):
        project_name = extract_project_name_from_data(request.data)
        enforce_project_write_by_name(
            request.user, project_name, RBACDomain.FINANCIAL
        )

        payload = self._clean_payload(request.data)
        planned_type = str(
            payload.get("planned_type") or PlannedEarnedValue.TYPE_SCL
        ).strip().upper()
        payload["planned_type"] = planned_type

        existing = _find_existing_record(
            project_name=str(payload.get("project_name") or project_name or "").strip(),
            planned_type=planned_type,
            month=payload.get("month"),
            year=payload.get("year"),
            contractor_id=payload.get("contractor_id"),
            contractor_name=payload.get("contractor_name"),
        )
        serializer = PlannedEarnedValueSerializer(
            existing,
            data=payload,
            partial=bool(existing),
            context={"request": request},
        )
        if not serializer.is_valid():
            return self._error(
                "Validation failed",
                errors=_flatten_errors(serializer.errors),
            )

        try:
            instance = serializer.save()
        except DjangoValidationError as exc:
            return self._error(
                "Validation failed",
                errors=_flatten_errors(getattr(exc, "message_dict", exc.messages)),
            )
        except Exception as exc:
            logger.exception("Planned vs Actual save failed: %s", exc)
            return self._error(
                "Failed to save Planned vs Actual record",
                errors=str(exc),
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        schedule_billing_update_notification_for_instance(
            request.user,
            instance,
            BillingModule.PLANNED_VS_ACTUAL,
            BillingAction.UPDATE if existing else BillingAction.CREATE,
        )

        return self._success(
            "Planned vs Actual saved successfully.",
            PlannedEarnedValueSerializer(instance).data,
            http_status=status.HTTP_200_OK if existing else status.HTTP_201_CREATED,
        )

    @swagger_auto_schema(operation_summary="List Planned vs Actual", tags=["Planned vs Actual"])
    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        export_fmt = (request.query_params.get("export") or "").lower()
        if export_fmt in {"csv", "excel", "xlsx", "xls", "pdf"}:
            return export_response(planned_vs_actual_rows(queryset), export_fmt)

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = PlannedEarnedValueSerializer(page, many=True)
            paginated = self.get_paginated_response(serializer.data)
            return Response(
                {
                    "success": True,
                    "message": "Planned vs Actual records retrieved successfully.",
                    "data": paginated.data,
                }
            )
        return self._success(
            "Planned vs Actual records retrieved successfully.",
            PlannedEarnedValueSerializer(queryset, many=True).data,
        )

    def retrieve(self, request, *args, **kwargs):
        try:
            instance = self.get_queryset().get(pk=kwargs["pk"])
        except PlannedEarnedValue.DoesNotExist:
            return self._error(
                "Planned vs Actual record not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )
        return self._success(
            "Planned vs Actual record retrieved successfully.",
            PlannedEarnedValueSerializer(instance).data,
        )

    @swagger_auto_schema(
        operation_summary="Update Planned vs Actual",
        request_body=_POST_SCHEMA,
        tags=["Planned vs Actual"],
    )
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        try:
            instance = PlannedEarnedValue.objects.select_related(
                "project", "contractor"
            ).get(pk=kwargs["pk"])
        except PlannedEarnedValue.DoesNotExist:
            return self._error(
                "Planned vs Actual record not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        enforce_instance_write(request.user, instance, RBACDomain.FINANCIAL)
        payload = self._clean_payload(request.data)
        serializer = PlannedEarnedValueSerializer(
            instance,
            data=payload,
            partial=partial,
            context={"request": request},
        )
        if not serializer.is_valid():
            return self._error(
                "Validation failed",
                errors=_flatten_errors(serializer.errors),
            )

        try:
            updated = serializer.save()
        except DjangoValidationError as exc:
            return self._error(
                "Validation failed",
                errors=_flatten_errors(getattr(exc, "message_dict", exc.messages)),
            )
        except Exception as exc:
            logger.exception("Planned vs Actual update failed: %s", exc)
            return self._error(
                "Failed to update Planned vs Actual record",
                errors=str(exc),
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        schedule_billing_update_notification_for_instance(
            request.user,
            updated,
            BillingModule.PLANNED_VS_ACTUAL,
            BillingAction.UPDATE,
        )
        return self._success(
            "Planned vs Actual updated successfully.",
            PlannedEarnedValueSerializer(updated).data,
        )

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        try:
            instance = PlannedEarnedValue.objects.get(pk=kwargs["pk"])
        except PlannedEarnedValue.DoesNotExist:
            return self._error(
                "Planned vs Actual record not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )
        enforce_instance_write(request.user, instance, RBACDomain.FINANCIAL)
        label = (
            f"{instance.project_name} [{instance.planned_type}] "
            f"{instance.month:02d}/{instance.year}"
        )
        schedule_billing_update_notification_for_instance(
            request.user,
            instance,
            BillingModule.PLANNED_VS_ACTUAL,
            BillingAction.DELETE,
        )
        instance.delete()
        return self._success(
            f"Planned vs Actual record for '{label}' deleted successfully.",
            {},
        )

    @swagger_auto_schema(
        operation_summary="Project-wise Planned vs Actual (SCL + contractors)",
        tags=["Planned vs Actual"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"project/(?P<projectName>[^/.]+)",
        url_name="by-project",
    )
    def by_project(self, request, projectName=None):
        project_name = (projectName or "").strip()
        if not project_name:
            return self._error("projectName is required.")
        enforce_project_access_by_name(request.user, project_name)

        qs = PlannedEarnedValue.objects.select_related("contractor").filter(
            project_name__iexact=project_name
        )

        month = request.query_params.get("month")
        year = request.query_params.get("year")
        if month:
            try:
                qs = qs.filter(month=int(month))
            except ValueError:
                return self._error("month must be a valid integer.")
        if year:
            try:
                qs = qs.filter(year=int(year))
            except ValueError:
                return self._error("year must be a valid integer.")

        qs = qs.order_by("year", "month", "planned_type", "contractor_name")
        project = resolve_project(normalize_project_name(project_name))
        display_name = project.name if project else project_name
        return self._success(
            "Project Planned vs Actual retrieved successfully.",
            _build_project_payload(display_name, list(qs)),
        )

    @swagger_auto_schema(
        operation_summary="Filter by planned type (SCL or CONTRACTOR)",
        tags=["Planned vs Actual"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"project/(?P<projectName>[^/.]+)/type/(?P<plannedType>[^/.]+)",
        url_name="by-type",
    )
    def by_type(self, request, projectName=None, plannedType=None):
        project_name = (projectName or "").strip()
        planned_type = (plannedType or "").strip().upper()
        if not project_name:
            return self._error("projectName is required.")
        if planned_type not in {
            PlannedEarnedValue.TYPE_SCL,
            PlannedEarnedValue.TYPE_CONTRACTOR,
        }:
            return self._error("plannedType must be SCL or CONTRACTOR.")

        enforce_project_access_by_name(request.user, project_name)

        month = request.query_params.get("month")
        year = request.query_params.get("year")
        contractor_id = request.query_params.get("contractor_id")

        qs = PlannedEarnedValue.objects.select_related("contractor").filter(
            project_name__iexact=project_name,
            planned_type=planned_type,
        )
        if month:
            try:
                qs = qs.filter(month=int(month))
            except ValueError:
                return self._error("month must be a valid integer.")
        if year:
            try:
                qs = qs.filter(year=int(year))
            except ValueError:
                return self._error("year must be a valid integer.")

        if planned_type == PlannedEarnedValue.TYPE_CONTRACTOR:
            if not contractor_id:
                if qs.count() > 1:
                    return self._error(
                        "contractor_id is required when multiple contractor records exist.",
                        errors={"contractor_id": "This field is required."},
                    )
            else:
                try:
                    qs = qs.filter(contractor_id=int(contractor_id))
                except ValueError:
                    return self._error("contractor_id must be a valid integer.")

        records = list(qs.order_by("year", "month", "contractor_name"))
        if planned_type == PlannedEarnedValue.TYPE_SCL:
            record = records[0] if records else None
            return self._success(
                "SCL Planned vs Actual retrieved successfully.",
                PlannedEarnedValueSerializer(record).data if record else None,
            )

        if contractor_id or len(records) <= 1:
            record = records[0] if records else None
            if record is None:
                return self._error(
                    "Contractor Planned vs Actual not found.",
                    http_status=status.HTTP_404_NOT_FOUND,
                )
            return self._success(
                "Contractor Planned vs Actual retrieved successfully.",
                {
                    "id": record.id,
                    "contractor_name": record.contractor_name,
                    "contractor": contractor_payload(record.contractor),
                    "planned_vs_actual": PlannedEarnedValueSerializer(record).data,
                },
            )

        return self._success(
            "Contractor Planned vs Actual records retrieved successfully.",
            [
                {
                    "id": r.id,
                    "contractor_name": r.contractor_name,
                    "contractor": contractor_payload(r.contractor),
                    "planned_vs_actual": PlannedEarnedValueSerializer(r).data,
                }
                for r in records
            ],
        )

    @swagger_auto_schema(
        operation_summary="Project monthly trend (Jan–Dec)",
        tags=["Planned vs Actual"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"project/(?P<projectName>[^/.]+)/trend",
        url_name="project-trend",
    )
    def project_trend(self, request, projectName=None):
        project_name = (projectName or "").strip()
        if not project_name:
            return self._error("projectName is required.")
        enforce_project_access_by_name(request.user, project_name)

        year_param = request.query_params.get("year")
        try:
            year = int(year_param) if year_param else timezone.now().year
        except ValueError:
            return self._error("year must be a valid integer.")

        records = list(
            PlannedEarnedValue.objects.select_related("contractor").filter(
                project_name__iexact=project_name,
                year=year,
            )
        )
        by_month: dict[int, list] = {m: [] for m in range(1, 13)}
        for record in records:
            by_month[record.month].append(record)

        months = []
        for month in range(1, 13):
            month_records = by_month[month]
            scl = next(
                (
                    r
                    for r in month_records
                    if r.planned_type == PlannedEarnedValue.TYPE_SCL
                ),
                None,
            )
            contractors = [
                r
                for r in month_records
                if r.planned_type == PlannedEarnedValue.TYPE_CONTRACTOR
            ]
            months.append(
                {
                    "month": month,
                    "month_name": month_abbr[month],
                    "scl": PlannedEarnedValueSerializer(scl).data if scl else None,
                    "contractor_summary": summary_to_api(
                        contractor_summary_from_records(contractors)
                        if contractors
                        else empty_summary()
                    ),
                    "contractors": [
                        {
                            "id": r.id,
                            "contractor_name": r.contractor_name,
                            "contractor": contractor_payload(r.contractor),
                            "planned_vs_actual": PlannedEarnedValueSerializer(r).data,
                        }
                        for r in contractors
                    ],
                }
            )

        project = resolve_project(normalize_project_name(project_name))
        return self._success(
            "Project Planned vs Actual trend retrieved successfully.",
            {
                "project_name": project.name if project else project_name,
                "year": year,
                "months": months,
            },
        )

    @swagger_auto_schema(
        operation_summary="Monthly dashboard across all projects",
        tags=["Planned vs Actual"],
    )
    @action(detail=False, methods=["get"], url_path="dashboard")
    def dashboard(self, request):
        month = request.query_params.get("month")
        year = request.query_params.get("year")
        try:
            month_int = int(month)
            year_int = int(year)
        except (TypeError, ValueError):
            return self._error("month and year are required integers.")

        if not (1 <= month_int <= 12):
            return self._error("month must be between 1 and 12.")
        if not (2000 <= year_int <= 2100):
            return self._error("year must be between 2000 and 2100.")

        accessible_projects = apply_project_rbac_to_queryset(
            Project.objects.all(),
            request,
            "name",
        )
        total_projects = accessible_projects.count()

        records = apply_project_rbac_to_queryset(
            PlannedEarnedValue.objects.filter(month=month_int, year=year_int),
            request,
            "project_name",
        )
        agg = records.aggregate(
            total_planned=Coalesce(Sum("planned_value"), Value(ZERO)),
            total_actual=Coalesce(Sum("actual_value"), Value(ZERO)),
            total_collection=Coalesce(Sum("collection"), Value(ZERO)),
            total_difference=Coalesce(Sum("difference"), Value(ZERO)),
            on_track=Count("id", filter=Q(variance_status="ON_TRACK")),
            minor=Count("id", filter=Q(variance_status="MINOR_VARIANCE")),
            major=Count("id", filter=Q(variance_status="MAJOR_VARIANCE")),
        )
        updated_names = set(
            records.values_list("project_name", flat=True).distinct()
        )
        updated = len({n.lower() for n in updated_names})

        total_planned = Decimal(agg["total_planned"] or 0)
        total_actual = Decimal(agg["total_actual"] or 0)
        total_collection = Decimal(agg["total_collection"] or 0)
        total_difference = Decimal(agg["total_difference"] or 0)

        return self._success(
            "Planned vs Actual dashboard retrieved successfully.",
            {
                "summary": {
                    "month": month_int,
                    "year": year_int,
                    "total_projects": total_projects,
                    "updated_projects": updated,
                    "pending_projects": max(total_projects - updated, 0),
                    "total_planned_value": float(total_planned),
                    "total_actual_value": float(total_actual),
                    "total_collection": float(total_collection),
                    "total_difference": float(total_difference),
                    "overall_achievement_percentage": _pct(total_actual, total_planned),
                    "overall_collection_percentage": _pct(
                        total_collection, total_actual
                    ),
                    "projects_on_track": agg["on_track"] or 0,
                    "projects_minor_variance": agg["minor"] or 0,
                    "projects_major_variance": agg["major"] or 0,
                }
            },
        )

    @swagger_auto_schema(
        operation_summary="Pending projects for a month",
        tags=["Planned vs Actual"],
    )
    @action(detail=False, methods=["get"], url_path="pending")
    def pending(self, request):
        month = request.query_params.get("month")
        year = request.query_params.get("year")
        try:
            month_int = int(month)
            year_int = int(year)
        except (TypeError, ValueError):
            return self._error("month and year are required integers.")

        accessible_projects = list(
            apply_project_rbac_to_queryset(
                Project.objects.all().order_by("name"),
                request,
                "name",
            )
        )
        period_records = PlannedEarnedValue.objects.filter(
            month=month_int,
            year=year_int,
        ).select_related("contractor")

        by_project: dict[str, list] = {}
        for record in period_records:
            key = record.project_name.lower()
            by_project.setdefault(key, []).append(record)

        active_contractors = {
            p.id: list(
                Contractor.objects.filter(
                    project=p,
                    status=Contractor.Status.ACTIVE,
                ).values_list("id", flat=True)
            )
            for p in accessible_projects
        }

        pending_projects = []
        for project in accessible_projects:
            records = by_project.get(project.name.lower(), [])
            has_scl = any(
                r.planned_type == PlannedEarnedValue.TYPE_SCL for r in records
            )
            contractor_ids_present = {
                r.contractor_id
                for r in records
                if r.planned_type == PlannedEarnedValue.TYPE_CONTRACTOR
                and r.contractor_id
            }
            expected_contractors = set(active_contractors.get(project.id, []))
            missing_contractors = bool(
                expected_contractors - contractor_ids_present
            )
            if not has_scl or missing_contractors:
                pending_projects.append(project.name)

        return self._success(
            "Pending Planned vs Actual projects retrieved successfully.",
            {
                "month": month_int,
                "year": year_int,
                "pending_projects": pending_projects,
                "count": len(pending_projects),
            },
        )


PlannedVsActualViewSet = PlannedEarnedValueViewSet
