"""Frequency chart client report + register CRUD."""

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status, viewsets
from rest_framework.response import Response

from ..models.frequency_chart import FrequencyChartEntry
from .frequency_chart_export import client_report_csv_response
from .frequency_chart_report import (
    CLIENT_FORMAT,
    EXPORT_CSV,
    VIEW_CUMULATIVE,
    VIEW_MONTHLY,
    build_client_report_payload,
    filter_frequency_chart_queryset,
    parse_report_params,
)
from .frequency_chart_serializer import FrequencyChartEntrySerializer
from .quality_status_controller import QualityStatusPagination


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


class FrequencyChartViewSet(viewsets.ModelViewSet):
    """Client frequency-chart report and register rows."""

    queryset = FrequencyChartEntry.objects.select_related("frequency_master").all()
    serializer_class = FrequencyChartEntrySerializer
    pagination_class = QualityStatusPagination
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]
    lookup_value_regex = r"\d+"

    def initial(self, request, *args, **kwargs):
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

    def _filtered_queryset(self, *, require_period: bool = False):
        params = self.request.query_params
        if require_period:
            parsed, error = parse_report_params(params, require_period=True)
            if error:
                return None, error
            return parsed, filter_frequency_chart_queryset(
                project_name=parsed["project_name"],
                month=parsed["month"],
                year=parsed["year"],
                view=parsed["view"],
                activity=parsed["activity"],
                test_type=parsed["test_type"],
                contractor=parsed["contractor"],
                search=parsed["search"],
                include_archived=parsed["include_archived"],
            )

        month = year = None
        if params.get("month"):
            try:
                month = int(params["month"])
            except ValueError:
                pass
        if params.get("year"):
            try:
                year = int(params["year"])
            except ValueError:
                pass

        include_archived = str(params.get("include_archived", "")).lower() in (
            "1",
            "true",
            "yes",
        )

        return None, filter_frequency_chart_queryset(
            project_name=params.get("project_name") or params.get("projectName"),
            month=month,
            year=year,
            view=params.get("view", VIEW_MONTHLY),
            activity=params.get("activity") or params.get("activity_name"),
            test_type=params.get("test_type") or params.get("type_of_test"),
            contractor=params.get("contractor") or params.get("contractor_name"),
            search=params.get("search"),
            include_archived=include_archived,
        )

    def get_queryset(self):
        _, queryset = self._filtered_queryset()
        return queryset

    @swagger_auto_schema(
        operation_summary="Frequency chart client report",
        manual_parameters=[
            openapi.Parameter("format", openapi.IN_QUERY, type=openapi.TYPE_STRING, enum=[CLIENT_FORMAT]),
            openapi.Parameter("project_name", openapi.IN_QUERY, type=openapi.TYPE_STRING),
            openapi.Parameter("month", openapi.IN_QUERY, type=openapi.TYPE_INTEGER),
            openapi.Parameter("year", openapi.IN_QUERY, type=openapi.TYPE_INTEGER),
            openapi.Parameter("view", openapi.IN_QUERY, type=openapi.TYPE_STRING, enum=[VIEW_MONTHLY, VIEW_CUMULATIVE]),
            openapi.Parameter("activity", openapi.IN_QUERY, type=openapi.TYPE_STRING),
            openapi.Parameter("test_type", openapi.IN_QUERY, type=openapi.TYPE_STRING),
            openapi.Parameter("contractor", openapi.IN_QUERY, type=openapi.TYPE_STRING),
            openapi.Parameter("search", openapi.IN_QUERY, type=openapi.TYPE_STRING),
            openapi.Parameter("export", openapi.IN_QUERY, type=openapi.TYPE_STRING, enum=[EXPORT_CSV]),
        ],
        tags=["Frequency Chart"],
    )
    def list(self, request, *args, **kwargs):
        if self._is_client_format(request):
            parsed, queryset = self._filtered_queryset(require_period=True)
            if parsed is None:
                return self._error(queryset)
            payload = build_client_report_payload(
                queryset,
                month=parsed["month"],
                year=parsed["year"],
                view=parsed["view"],
                project_name=parsed.get("project_name"),
            )
            if request.query_params.get("export", "").lower() == EXPORT_CSV:
                return client_report_csv_response(payload["rows"])
            return self._success(
                "Frequency chart client report retrieved successfully",
                payload,
            )

        return self._error(
            "Use format=client for the frequency chart report, "
            "or POST/GET /api/frequency-chart/register/ for register CRUD."
        )

    def create(self, request, *args, **kwargs):
        return self._error(
            "Use POST /api/frequency-chart/register/ to create register rows."
        )


class FrequencyChartRegisterViewSet(viewsets.ModelViewSet):
    """CRUD for frequency chart register rows."""

    queryset = FrequencyChartEntry.objects.select_related("frequency_master").all()
    serializer_class = FrequencyChartEntrySerializer
    pagination_class = QualityStatusPagination
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]
    lookup_value_regex = r"\d+"

    def initial(self, request, *args, **kwargs):
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

    def _filtered_queryset(self, *, require_period: bool = False):
        params = self.request.query_params
        if require_period:
            parsed, error = parse_report_params(params, require_period=True)
            if error:
                return None, error
            return parsed, filter_frequency_chart_queryset(
                project_name=parsed["project_name"],
                month=parsed["month"],
                year=parsed["year"],
                view=parsed["view"],
                activity=parsed["activity"],
                test_type=parsed["test_type"],
                contractor=parsed["contractor"],
                search=parsed["search"],
                include_archived=parsed["include_archived"],
            )

        month = year = None
        if params.get("month"):
            try:
                month = int(params["month"])
            except ValueError:
                pass
        if params.get("year"):
            try:
                year = int(params["year"])
            except ValueError:
                pass

        include_archived = str(params.get("include_archived", "")).lower() in (
            "1",
            "true",
            "yes",
        )

        return None, filter_frequency_chart_queryset(
            project_name=params.get("project_name") or params.get("projectName"),
            month=month,
            year=year,
            view=params.get("view", VIEW_MONTHLY),
            activity=params.get("activity") or params.get("activity_name"),
            test_type=params.get("test_type") or params.get("type_of_test"),
            contractor=params.get("contractor") or params.get("contractor_name"),
            search=params.get("search"),
            include_archived=include_archived,
        )

    def get_queryset(self):
        _, queryset = self._filtered_queryset()
        return queryset

    def list(self, request, *args, **kwargs):
        if self._is_client_format(request):
            parsed, queryset = self._filtered_queryset(require_period=True)
            if parsed is None:
                return self._error(queryset)
            payload = build_client_report_payload(
                queryset,
                month=parsed["month"],
                year=parsed["year"],
                view=parsed["view"],
                project_name=parsed.get("project_name"),
            )
            if request.query_params.get("export", "").lower() == EXPORT_CSV:
                return client_report_csv_response(payload["rows"])
            return self._success(
                "Frequency chart client report retrieved successfully",
                payload,
            )

        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            paginated = self.get_paginated_response(serializer.data)
            return self._success(
                "Frequency chart register rows retrieved successfully",
                paginated.data,
            )

        serializer = self.get_serializer(queryset, many=True)
        return self._success(
            "Frequency chart register rows retrieved successfully",
            serializer.data,
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return self._error("Validation failed", errors=_flatten_errors(serializer.errors))
        try:
            instance = serializer.save()
        except DjangoValidationError as exc:
            return self._error("Validation failed", errors=_flatten_errors(exc.message_dict))
        return self._success(
            "Frequency chart row created successfully",
            self.get_serializer(instance).data,
            http_status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        try:
            instance = FrequencyChartEntry.objects.select_related("frequency_master").get(
                pk=kwargs["pk"]
            )
        except FrequencyChartEntry.DoesNotExist:
            return self._error("Frequency chart row not found", http_status=status.HTTP_404_NOT_FOUND)

        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        if not serializer.is_valid():
            return self._error("Validation failed", errors=_flatten_errors(serializer.errors))
        try:
            updated = serializer.save()
        except DjangoValidationError as exc:
            return self._error("Validation failed", errors=_flatten_errors(exc.message_dict))
        return self._success(
            "Frequency chart row updated successfully",
            self.get_serializer(updated).data,
        )

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        try:
            instance = FrequencyChartEntry.objects.get(pk=kwargs["pk"])
        except FrequencyChartEntry.DoesNotExist:
            return self._error("Frequency chart row not found", http_status=status.HTTP_404_NOT_FOUND)
        label = f"{instance.item_description} (#{instance.sr_no})"
        instance.delete()
        return self._success(f"Frequency chart row '{label}' deleted successfully", {})
