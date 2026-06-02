"""
Drawing Summary Controller (ViewSet).

  POST   /api/drawings/
  GET    /api/drawings/
  GET    /api/drawings/{id}/
  PUT    /api/drawings/{id}/
  PATCH  /api/drawings/{id}/
  DELETE /api/drawings/{id}/
  GET    /api/drawings/project/{projectName}/                    (legacy → project summary)
  GET    /api/drawings/project/{projectName}/month/{m}/year/{y}/
  GET    /api/drawings/project/{projectName}/summary/
  GET    /api/drawings/project/{projectName}/year/{year}/summary/
  GET    /api/drawings/project/{projectName}/dashboard/
"""

from datetime import date

from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Sum, Value
from django.db.models.functions import Coalesce
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from ..models.drawing import DrawingSummary
from .drawing_metrics import metrics_from_counts, monthly_response, compact_metrics
from .drawing_serializer import DrawingSerializer

_FIELD_ALIASES: dict[str, str] = {
    "project_name": "_project_name",
    "projectName": "_project_name",
    "submitted_drawings": "submitted_drawings",
    "approved_drawings": "approved_drawings",
    "totalSubmitted": "submitted_drawings",
    "totalApproved": "approved_drawings",
}

_STRIP_FIELDS: set[str] = {
    "variance",
    "approval_rate",
    "approval_percentage",
    "approvalPercentage",
    "projectName",
    "project_name",
}


def _normalise_payload(data: dict) -> dict:
    normalised: dict = {}
    for key, value in data.items():
        if key in _STRIP_FIELDS:
            continue
        canonical_key = _FIELD_ALIASES.get(key, key)
        normalised[canonical_key] = value

    for field in ("submitted_drawings", "approved_drawings", "month", "year"):
        if field in normalised:
            try:
                normalised[field] = int(normalised[field])
            except (TypeError, ValueError):
                pass

    return normalised


def _flatten_errors(errors) -> dict:
    flat: dict = {}
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


def _aggregate_queryset(queryset) -> dict:
    agg = queryset.aggregate(
        submitted=Coalesce(Sum("submitted_drawings"), Value(0)),
        approved=Coalesce(Sum("approved_drawings"), Value(0)),
    )
    return metrics_from_counts(agg["submitted"], agg["approved"])


_CACHE_KEY_LIST = "drawings_list"
_CACHE_TIMEOUT = 300


class DrawingPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


_DRAWING_POST_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    required=["project_name", "month", "year"],
    properties={
        "project_name": openapi.Schema(type=openapi.TYPE_STRING, example="Thane Project"),
        "month": openapi.Schema(type=openapi.TYPE_INTEGER, example=6),
        "year": openapi.Schema(type=openapi.TYPE_INTEGER, example=2026),
        "submitted_drawings": openapi.Schema(type=openapi.TYPE_INTEGER, example=120),
        "approved_drawings": openapi.Schema(type=openapi.TYPE_INTEGER, example=90),
    },
)

_DRAWING_RESPONSE_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    properties={
        "success": openapi.Schema(type=openapi.TYPE_BOOLEAN, example=True),
        "message": openapi.Schema(type=openapi.TYPE_STRING),
        "data": openapi.Schema(type=openapi.TYPE_OBJECT),
    },
)


class DrawingViewSet(viewsets.ModelViewSet):
    """
    Monthly Drawing Summary ViewSet.

    One record per (project, month, year).
    variance and approval_rate are computed on read — never stored.
    """

    queryset = DrawingSummary.objects.select_related("project").all()
    serializer_class = DrawingSerializer
    permission_classes = [AllowAny]
    pagination_class = DrawingPagination

    def get_queryset(self):
        qs = DrawingSummary.objects.select_related("project").all()

        project_name = self.request.query_params.get("project_name")
        if project_name:
            qs = qs.filter(project__name__icontains=project_name.strip())

        year = self.request.query_params.get("year")
        if year:
            try:
                qs = qs.filter(year=int(year))
            except ValueError:
                pass

        month = self.request.query_params.get("month")
        if month:
            try:
                qs = qs.filter(month=int(month))
            except ValueError:
                pass

        return qs.order_by("project__name", "year", "month")

    def _invalidate_list_cache(self):
        cache.delete(_CACHE_KEY_LIST)

    def _success_response(self, message: str, data, http_status=status.HTTP_200_OK):
        return Response(
            {"success": True, "message": message, "data": data},
            status=http_status,
        )

    def _error_response(self, message: str, errors=None, http_status=status.HTTP_400_BAD_REQUEST):
        payload = {"success": False, "message": message}
        if errors is not None:
            payload["errors"] = errors
        return Response(payload, status=http_status)

    def _find_monthly_record(self, project_name: str, month: int, year: int):
        return (
            DrawingSummary.objects.select_related("project")
            .filter(
                project__name__iexact=project_name.strip(),
                month=month,
                year=year,
            )
            .first()
        )

    def _project_queryset(self, project_name: str):
        return DrawingSummary.objects.filter(
            project__name__iexact=project_name.strip()
        )

    def _upsert_from_payload(self, payload: dict):
        project_name = payload.get("_project_name", "").strip()
        month = payload.get("month")
        year = payload.get("year")

        existing = None
        if project_name and month is not None and year is not None:
            existing = self._find_monthly_record(project_name, int(month), int(year))

        if existing is not None:
            serializer = DrawingSerializer(existing, data=payload)
        else:
            serializer = DrawingSerializer(data=payload)

        return serializer, existing

    @swagger_auto_schema(
        operation_summary="Create Drawing Summary Record",
        request_body=_DRAWING_POST_SCHEMA,
        responses={201: openapi.Response("Created", _DRAWING_RESPONSE_SCHEMA), 400: "Validation error"},
        tags=["Drawings"],
    )
    def create(self, request, *args, **kwargs):
        """Create or update monthly drawing summary (upsert by project + month + year)."""
        payload = _normalise_payload(request.data)

        if "_project_name" not in payload and "project_name" in request.data:
            payload["_project_name"] = str(request.data.get("project_name", "")).strip()
        if "_project_name" not in payload and "projectName" in request.data:
            payload["_project_name"] = str(request.data.get("projectName", "")).strip()

        serializer, existing = self._upsert_from_payload(payload)

        if not serializer.is_valid():
            return self._error_response(
                "Validation failed",
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
            "Drawing summary updated successfully"
            if existing
            else "Drawing summary saved successfully"
        )

        return self._success_response(
            message,
            DrawingSerializer(instance).data,
            http_status=http_status,
        )

    @swagger_auto_schema(
        operation_summary="Get All Drawing Summary Records",
        manual_parameters=[
            openapi.Parameter("project_name", openapi.IN_QUERY, type=openapi.TYPE_STRING, required=False),
            openapi.Parameter("month", openapi.IN_QUERY, type=openapi.TYPE_INTEGER, required=False),
            openapi.Parameter("year", openapi.IN_QUERY, type=openapi.TYPE_INTEGER, required=False),
        ],
        responses={200: openapi.Response("OK", _DRAWING_RESPONSE_SCHEMA)},
        tags=["Drawings"],
    )
    def list(self, request, *args, **kwargs):
        has_filters = any(
            request.query_params.get(k) for k in ("project_name", "month", "year")
        )
        page_param = request.query_params.get("page", "1")
        use_cache = not has_filters and page_param == "1"

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

    @swagger_auto_schema(
        operation_summary="Get Drawing Summary by ID",
        responses={200: openapi.Response("OK", _DRAWING_RESPONSE_SCHEMA), 404: "Not found"},
        tags=["Drawings"],
    )
    def retrieve(self, request, *args, **kwargs):
        try:
            instance = DrawingSummary.objects.select_related("project").get(pk=kwargs["pk"])
        except DrawingSummary.DoesNotExist:
            return self._error_response("Drawing not found", http_status=status.HTTP_404_NOT_FOUND)

        return self._success_response(
            "Drawing record retrieved successfully",
            DrawingSerializer(instance).data,
        )

    @swagger_auto_schema(
        operation_summary="Update Drawing Summary",
        request_body=_DRAWING_POST_SCHEMA,
        responses={200: openapi.Response("OK", _DRAWING_RESPONSE_SCHEMA), 400: "Validation error", 404: "Not found"},
        tags=["Drawings"],
    )
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)

        try:
            instance = DrawingSummary.objects.select_related("project").get(pk=kwargs["pk"])
        except DrawingSummary.DoesNotExist:
            return self._error_response("Drawing not found", http_status=status.HTTP_404_NOT_FOUND)

        payload = _normalise_payload(request.data)
        if "_project_name" not in payload and "project_name" in request.data:
            payload["_project_name"] = str(request.data.get("project_name", "")).strip()

        serializer = DrawingSerializer(instance, data=payload, partial=partial)

        if not serializer.is_valid():
            return self._error_response(
                "Validation failed",
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
            "Drawing summary updated successfully",
            DrawingSerializer(updated_instance).data,
        )

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Delete Drawing Summary",
        responses={200: openapi.Response("OK"), 404: "Not found"},
        tags=["Drawings"],
    )
    def destroy(self, request, *args, **kwargs):
        try:
            instance = DrawingSummary.objects.select_related("project").get(pk=kwargs["pk"])
        except DrawingSummary.DoesNotExist:
            return self._error_response("Drawing not found", http_status=status.HTTP_404_NOT_FOUND)

        label = f"{instance.project_name} ({instance.month:02d}/{instance.year})"
        instance.delete()
        self._invalidate_list_cache()

        return self._success_response(
            f"Drawing summary for '{label}' deleted successfully",
            {},
        )

    # -------------------------------------------------------------------------
    # MONTHLY  GET .../project/{projectName}/month/{month}/year/{year}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get drawing summary for a specific month",
        responses={200: openapi.Response("OK"), 404: "Not found"},
        tags=["Drawings"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"project/(?P<projectName>[^/.]+)/month/(?P<month>\d+)/year/(?P<year>\d+)",
        url_name="by-month-year",
    )
    def get_by_month_year(self, request, projectName=None, month=None, year=None):
        try:
            month_int = int(month)
            year_int = int(year)
        except (TypeError, ValueError):
            return self._error_response("month and year must be valid integers.")

        if not (1 <= month_int <= 12):
            return self._error_response("month must be between 1 and 12.")
        if not (2000 <= year_int <= 2100):
            return self._error_response("year must be between 2000 and 2100.")

        project_name = projectName.strip()
        instance = self._find_monthly_record(project_name, month_int, year_int)

        if instance is None:
            return self._error_response(
                f"No drawing summary found for '{project_name}' in {month_int:02d}/{year_int}.",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        return self._success_response(
            f"Drawing summary for '{project_name}' ({month_int:02d}/{year_int}) retrieved successfully",
            monthly_response(instance),
        )

    # -------------------------------------------------------------------------
    # PROJECT SUMMARY  GET .../project/{projectName}/summary/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Project-wide drawing summary (all months, SUM)",
        responses={200: openapi.Response("OK"), 404: "Not found"},
        tags=["Drawings"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"project/(?P<projectName>[^/.]+)/summary",
        url_name="project-summary",
    )
    def project_summary(self, request, projectName=None):
        if not projectName or not projectName.strip():
            return self._error_response("projectName is required.")

        project_name = projectName.strip()
        qs = self._project_queryset(project_name)

        if not qs.exists():
            return self._error_response(
                f"No drawing summary records found for project '{project_name}'",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        metrics = _aggregate_queryset(qs)
        return self._success_response(
            f"Project drawing summary for '{project_name}' retrieved successfully",
            {"project_name": project_name, **metrics},
        )

    # -------------------------------------------------------------------------
    # YEARLY SUMMARY  GET .../project/{projectName}/year/{year}/summary/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Yearly drawing summary (SUM for selected year)",
        responses={200: openapi.Response("OK"), 404: "Not found"},
        tags=["Drawings"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"project/(?P<projectName>[^/.]+)/year/(?P<year>\d+)/summary",
        url_name="yearly-summary",
    )
    def yearly_summary(self, request, projectName=None, year=None):
        try:
            year_int = int(year)
        except (TypeError, ValueError):
            return self._error_response("year must be a valid integer.")

        if not (2000 <= year_int <= 2100):
            return self._error_response("year must be between 2000 and 2100.")

        project_name = projectName.strip()
        qs = self._project_queryset(project_name).filter(year=year_int)

        if not qs.exists():
            return self._error_response(
                f"No drawing summary records found for '{project_name}' in {year_int}.",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        metrics = _aggregate_queryset(qs)
        return self._success_response(
            f"Yearly drawing summary for '{project_name}' ({year_int}) retrieved successfully",
            {"project_name": project_name, "year": year_int, **metrics},
        )

    # -------------------------------------------------------------------------
    # DASHBOARD  GET .../project/{projectName}/dashboard/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Dashboard — current month + project totals",
        responses={200: openapi.Response("OK"), 404: "Not found"},
        tags=["Drawings"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"project/(?P<projectName>[^/.]+)/dashboard",
        url_name="dashboard",
    )
    def dashboard(self, request, projectName=None):
        if not projectName or not projectName.strip():
            return self._error_response("projectName is required.")

        project_name = projectName.strip()
        qs = self._project_queryset(project_name)

        if not qs.exists():
            return self._error_response(
                f"No drawing summary records found for project '{project_name}'",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        today = date.today()
        current_month_record = self._find_monthly_record(
            project_name, today.month, today.year
        )

        project_metrics = _aggregate_queryset(qs)

        return self._success_response(
            f"Drawing dashboard for '{project_name}' retrieved successfully",
            {
                "project_name": project_name,
                "current_month": compact_metrics(current_month_record),
                "project_summary": {
                    "submitted_drawings": project_metrics["submitted_drawings"],
                    "approved_drawings": project_metrics["approved_drawings"],
                    "variance": project_metrics["variance"],
                    "approval_rate": project_metrics["approval_rate"],
                },
            },
        )

    # -------------------------------------------------------------------------
    # LEGACY  GET .../project/{projectName}/  → project summary
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get drawing summary by project name (legacy)",
        operation_description="Returns aggregated project summary (same as /summary/).",
        responses={200: openapi.Response("OK", _DRAWING_RESPONSE_SCHEMA), 404: "Not found"},
        tags=["Drawings"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"project/(?P<projectName>[^/.]+)",
        url_name="by-project-name",
    )
    def get_by_project_name(self, request, projectName: str = None):
        """Backward-compatible alias for project-wide aggregated summary."""
        return self.project_summary(request, projectName=projectName)
