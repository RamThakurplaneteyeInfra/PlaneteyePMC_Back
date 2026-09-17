"""
Drawing Controller.

DrawingSummary (legacy KPI model) is no longer the source of truth.
All KPI metrics are computed directly from DrawingRegisterItem records.

Active endpoints:
  GET  /api/drawings/project/{projectName}/summary/?month={m}&year={y}
  GET  /api/drawings/project/{projectName}/summary/?month={m}&year={y}&view=cumulative

Register CRUD (DrawingRegisterViewSet):
  GET    /api/drawings/register/
  POST   /api/drawings/register/
  PATCH  /api/drawings/register/{id}/
  DELETE /api/drawings/register/{id}/
"""

from datetime import date

from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status, viewsets
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from .drawing_metrics import metrics_from_counts
from .drawing_report import (
    CLIENT_FORMAT,
    EXPORT_CSV,
    VIEW_CUMULATIVE,
    VIEW_MONTHLY,
    build_client_report_payload,
    filter_register_queryset,
    kpi_summary_for_period,
    normalize_view,
    parse_report_params,
    period_date_range,
)
from .drawing_export import client_report_csv_response


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


class DrawingPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


_DRAWING_RESPONSE_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    properties={
        "success": openapi.Schema(type=openapi.TYPE_BOOLEAN, example=True),
        "message": openapi.Schema(type=openapi.TYPE_STRING),
        "data": openapi.Schema(type=openapi.TYPE_OBJECT),
    },
)


class DrawingViewSet(viewsets.GenericViewSet):
    """
    Read-only ViewSet for drawing KPI summaries.

    All metrics are derived from DrawingRegisterItem records — no separate
    summary model is maintained.
    """

    pagination_class = DrawingPagination

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

    def initial(self, request, *args, **kwargs):
        """
        DRF treats ?format= as a response renderer suffix.
        ?format=client is our report shape — strip it before negotiation.
        """
        self._client_format_query = False
        raw_get = getattr(request, "_request", request).GET
        if hasattr(raw_get, "get") and raw_get.get("format", "").lower() == CLIENT_FORMAT:
            self._client_format_query = True
            mutable = raw_get.copy()
            mutable.pop("format", None)
            request._request.GET = mutable
        super().initial(request, *args, **kwargs)

    def _is_client_format(self, request) -> bool:
        if getattr(self, "_client_format_query", False):
            return True
        return str(request.query_params.get("report_format", "")).lower() == CLIENT_FORMAT

    def _parse_period_filters(self, request, *, project_name: str | None = None):
        parsed, error = parse_report_params(
            request.query_params,
            project_name=project_name,
            require_period=True,
        )
        if error:
            return None, error
        queryset = filter_register_queryset(
            project_name=parsed["project_name"],
            month=parsed["month"],
            year=parsed["year"],
            view=parsed["view"],
            contractor=parsed["contractor"],
            status=parsed["status"],
            search=parsed["search"],
        )
        return parsed, queryset

    def _period_kpi_response(self, project_name: str, parsed: dict, message: str):
        metrics = kpi_summary_for_period(
            project_name,
            parsed["month"],
            parsed["year"],
            parsed["view"],
        )
        from_date, to_date = period_date_range(
            parsed["year"], parsed["month"], parsed["view"]
        )
        return self._success_response(
            message,
            {
                "view": parsed["view"],
                "from_date": from_date.isoformat(),
                "to_date": to_date.isoformat(),
                "project_name": project_name,
                "month": parsed["month"],
                "year": parsed["year"],
                **metrics,
            },
        )

    def _client_report_response(self, request, parsed: dict, queryset, message: str):
        payload = build_client_report_payload(
            queryset,
            month=parsed["month"],
            year=parsed["year"],
            view=parsed["view"],
            project_name=parsed.get("project_name"),
        )
        if request.query_params.get("export", "").lower() == EXPORT_CSV:
            return client_report_csv_response(payload["rows"])
        return self._success_response(message, payload)

    # -------------------------------------------------------------------------
    # GET /api/drawings/project/{projectName}/summary/?month=&year=[&view=]
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Drawing KPI summary for a project/month/year",
        operation_description=(
            "Returns submitted_drawings, approved_drawings, variance, and approval_rate "
            "computed directly from Drawing Register records. "
            "Pass view=cumulative for year-to-date totals."
        ),
        manual_parameters=[
            openapi.Parameter(
                "month", openapi.IN_QUERY, type=openapi.TYPE_INTEGER, required=True,
                description="Month number (1–12)",
            ),
            openapi.Parameter(
                "year", openapi.IN_QUERY, type=openapi.TYPE_INTEGER, required=True,
                description="Four-digit year",
            ),
            openapi.Parameter(
                "view", openapi.IN_QUERY, type=openapi.TYPE_STRING,
                enum=[VIEW_MONTHLY, VIEW_CUMULATIVE],
                description="monthly (default) or cumulative (year-to-date)",
            ),
        ],
        responses={200: openapi.Response("OK", _DRAWING_RESPONSE_SCHEMA), 400: "Bad request"},
        tags=["Drawings"],
    )
    def project_summary(self, request, projectName=None):
        """
        KPI dashboard endpoint.

        GET /api/drawings/project/{projectName}/summary/?month=6&year=2026
        GET /api/drawings/project/{projectName}/summary/?month=6&year=2026&view=cumulative
        """
        if not projectName or not projectName.strip():
            return self._error_response("projectName is required.")

        project_name = projectName.strip()

        # Client report format (optional)
        if self._is_client_format(request):
            parsed, register_qs = self._parse_period_filters(
                request, project_name=project_name
            )
            if parsed is None:
                return self._error_response(register_qs)
            return self._client_report_response(
                request,
                parsed,
                register_qs,
                f"Client drawing report for '{project_name}' retrieved successfully",
            )

        # Standard KPI summary — requires month + year
        parsed, error = parse_report_params(
            request.query_params,
            project_name=project_name,
            require_period=True,
        )
        if error:
            return self._error_response(error)

        return self._period_kpi_response(
            project_name,
            parsed,
            f"Drawing {parsed['view']} summary for '{project_name}' "
            f"({parsed['month']:02d}/{parsed['year']}) retrieved successfully",
        )
