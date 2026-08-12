"""CRUD for per-drawing register rows (client report source data)."""

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status, viewsets
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from ..models.drawing_register import DrawingRegisterItem
from ..services.file_upload import (
    collect_drawing_files,
    delete_register_s3_files,
    persist_drawing_files,
    prepare_register_payload,
    validate_all_uploads,
)
from services.billing_update_notifications import (
    BillingAction,
    BillingModule,
    schedule_billing_update_notification_for_instance,
)
from .drawing_controller import DrawingPagination, _flatten_errors
from .drawing_export import client_report_csv_response
from .drawing_report import (
    CLIENT_FORMAT,
    EXPORT_CSV,
    REGISTER_LIST_PREFETCHES,
    VIEW_CUMULATIVE,
    VIEW_MONTHLY,
    build_client_report_payload,
    filter_register_queryset,
    parse_report_params,
)
from .drawing_register_serializer import DrawingRegisterItemSerializer


class DrawingRegisterViewSet(viewsets.ModelViewSet):
    """Individual drawing register rows + workflow history."""

    queryset = DrawingRegisterItem.objects.select_related("project").prefetch_related(
        *REGISTER_LIST_PREFETCHES,
    )
    serializer_class = DrawingRegisterItemSerializer
    pagination_class = DrawingPagination
    parser_classes = [JSONParser, MultiPartParser, FormParser]
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
        report_format = request.query_params.get("report_format", "")
        return str(report_format).lower() == CLIENT_FORMAT

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
            return parsed, filter_register_queryset(
                project_name=parsed["project_name"],
                month=parsed["month"],
                year=parsed["year"],
                view=parsed["view"],
                contractor=parsed["contractor"],
                status=parsed["status"],
                search=parsed["search"],
            ).prefetch_related(*REGISTER_LIST_PREFETCHES)

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

        return None, filter_register_queryset(
            project_name=params.get("project_name"),
            month=month,
            year=year,
            view=params.get("view", VIEW_MONTHLY),
            contractor=params.get("contractor"),
            status=params.get("status"),
            search=params.get("search"),
        ).prefetch_related(*REGISTER_LIST_PREFETCHES)

    def get_queryset(self):
        _, queryset = self._filtered_queryset()
        return queryset

    @swagger_auto_schema(
        operation_summary="List drawing register rows",
        manual_parameters=[
            openapi.Parameter("project_name", openapi.IN_QUERY, type=openapi.TYPE_STRING),
            openapi.Parameter("month", openapi.IN_QUERY, type=openapi.TYPE_INTEGER),
            openapi.Parameter("year", openapi.IN_QUERY, type=openapi.TYPE_INTEGER),
            openapi.Parameter(
                "view",
                openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                enum=[VIEW_MONTHLY, VIEW_CUMULATIVE],
            ),
            openapi.Parameter("contractor", openapi.IN_QUERY, type=openapi.TYPE_STRING),
            openapi.Parameter("status", openapi.IN_QUERY, type=openapi.TYPE_STRING),
            openapi.Parameter("search", openapi.IN_QUERY, type=openapi.TYPE_STRING),
            openapi.Parameter(
                "format",
                openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                enum=[CLIENT_FORMAT],
            ),
            openapi.Parameter(
                "export",
                openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                enum=[EXPORT_CSV],
            ),
        ],
        tags=["Drawings"],
    )
    def list(self, request, *args, **kwargs):
        client_format = self._is_client_format(request)

        if client_format:
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
            export = request.query_params.get("export", "").lower()
            if export == EXPORT_CSV:
                return client_report_csv_response(payload["rows"])
            return self._success(
                "Client drawing report retrieved successfully",
                payload,
            )

        queryset = self.get_queryset()

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            paginated = self.get_paginated_response(serializer.data)
            return self._success(
                "Drawing register rows retrieved successfully",
                paginated.data,
            )

        serializer = self.get_serializer(queryset, many=True)
        return self._success(
            "Drawing register rows retrieved successfully",
            serializer.data,
        )

    def create(self, request, *args, **kwargs):
        uploaded_files = collect_drawing_files(request)
        try:
            validate_all_uploads(uploaded_files)
        except DjangoValidationError as exc:
            return self._error(
                "Validation failed",
                errors=_flatten_errors(exc.message_dict),
            )

        payload = prepare_register_payload(request.data)
        serializer = self.get_serializer(data=payload)
        if not serializer.is_valid():
            return self._error(
                "Validation failed",
                errors=_flatten_errors(serializer.errors),
            )
        try:
            instance = serializer.save()
        except DjangoValidationError as exc:
            return self._error(
                "Validation failed", errors=_flatten_errors(exc.message_dict)
            )

        try:
            if uploaded_files:
                persist_drawing_files(
                    register_item=instance,
                    uploaded_files=uploaded_files,
                    actor=request.user,
                )
        except Exception as exc:
            delete_register_s3_files(instance)
            instance.delete()
            if isinstance(exc, DjangoValidationError):
                return self._error(
                    "Validation failed",
                    errors=_flatten_errors(exc.message_dict),
                )
            return self._error(
                "Drawing file upload failed",
                errors={"drawings": str(exc)},
            )

        instance = (
            DrawingRegisterItem.objects.select_related("project")
            .prefetch_related(*REGISTER_LIST_PREFETCHES)
            .get(pk=instance.pk)
        )
        schedule_billing_update_notification_for_instance(
            request.user,
            instance,
            BillingModule.DRAWING_SUMMARY,
            BillingAction.CREATE,
        )
        return self._success(
            "Drawing register row created successfully",
            self.get_serializer(instance).data,
            http_status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        uploaded_files = collect_drawing_files(request)
        try:
            validate_all_uploads(uploaded_files)
        except DjangoValidationError as exc:
            return self._error(
                "Validation failed",
                errors=_flatten_errors(exc.message_dict),
            )

        try:
            instance = DrawingRegisterItem.objects.select_related("project").get(
                pk=kwargs["pk"]
            )
        except DrawingRegisterItem.DoesNotExist:
            return self._error(
                "Drawing register row not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        payload = prepare_register_payload(request.data)
        serializer = self.get_serializer(instance, data=payload, partial=partial)
        if not serializer.is_valid():
            return self._error(
                "Validation failed",
                errors=_flatten_errors(serializer.errors),
            )
        try:
            updated = serializer.save()
        except DjangoValidationError as exc:
            return self._error(
                "Validation failed", errors=_flatten_errors(exc.message_dict)
            )

        if uploaded_files:
            try:
                persist_drawing_files(
                    register_item=updated,
                    uploaded_files=uploaded_files,
                    actor=request.user,
                    revision=updated.revision,
                )
            except Exception as exc:
                if isinstance(exc, DjangoValidationError):
                    return self._error(
                        "Validation failed",
                        errors=_flatten_errors(exc.message_dict),
                    )
                return self._error(
                    "Drawing file upload failed",
                    errors={"drawings": str(exc)},
                )

        updated = (
            DrawingRegisterItem.objects.select_related("project")
            .prefetch_related(*REGISTER_LIST_PREFETCHES)
            .get(pk=updated.pk)
        )
        schedule_billing_update_notification_for_instance(
            request.user,
            updated,
            BillingModule.DRAWING_SUMMARY,
            BillingAction.UPDATE,
        )
        return self._success(
            "Drawing register row updated successfully",
            self.get_serializer(updated).data,
        )

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        try:
            instance = DrawingRegisterItem.objects.get(pk=kwargs["pk"])
        except DrawingRegisterItem.DoesNotExist:
            return self._error(
                "Drawing register row not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )
        label = f"{instance.drawing_name} (#{instance.sr_no})"
        schedule_billing_update_notification_for_instance(
            request.user,
            instance,
            BillingModule.DRAWING_SUMMARY,
            BillingAction.DELETE,
        )
        delete_register_s3_files(instance)
        instance.delete()
        return self._success(f"Drawing register row '{label}' deleted successfully", {})
