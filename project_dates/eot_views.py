"""
Project EOT ViewSet — multiple Extension of Time records per project.

Endpoints:
  GET/POST   /api/project-eot/
  GET/PATCH/PUT/DELETE /api/project-eot/{id}/
  GET        /api/project-eot/project/{projectName}/
"""

from __future__ import annotations

import logging
from urllib.parse import unquote

from django.core.exceptions import ValidationError as DjangoValidationError
from django_filters.rest_framework import DjangoFilterBackend
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from accounts.permissions import IsAuthenticatedProjectRBAC
from accounts.rbac import RBACDomain, filter_queryset_by_project_access
from contractors.resolvers import resolve_project_for_module
from core.business_audit import write_business_audit
from core.models import BusinessAuditLog
from project_dates.eot_filters import ProjectEOTFilter
from project_dates.eot_models import ProjectEOT
from project_dates.eot_serializers import ProjectEOTSerializer
from project_dates.eot_services import (
    invalidate_eot_caches,
    project_eot_summary,
    soft_delete_eot,
    sync_legacy_eot_date,
)

logger = logging.getLogger("pmc.eot")


class LegacyEOTOrderingFilter(filters.OrderingFilter):
    """Accept legacy Project Dates ordering keys (eot_date, contract_finish, …)."""

    ALIASES = {
        "eot_date": "revised_completion_date",
        "-eot_date": "-revised_completion_date",
        "contract_finish": "original_completion_date",
        "-contract_finish": "-original_completion_date",
        "project_name": "project__name",
        "-project_name": "-project__name",
    }

    def get_ordering(self, request, queryset, view):
        ordering = super().get_ordering(request, queryset, view)
        if not ordering:
            return ordering
        return [self.ALIASES.get(item, item) for item in ordering]


class ProjectEOTPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class ProjectEOTViewSet(viewsets.ModelViewSet):
    """CRUD for multi-EOT history. Soft-delete on destroy."""

    serializer_class = ProjectEOTSerializer
    permission_classes = [IsAuthenticatedProjectRBAC]
    rbac_domain = RBACDomain.GENERAL
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    pagination_class = ProjectEOTPagination
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        LegacyEOTOrderingFilter,
    ]
    filterset_class = ProjectEOTFilter
    search_fields = [
        "reason",
        "remarks",
        "project__name",
        "status",
        "eot_number",
    ]
    ordering_fields = [
        "eot_number",
        "extension_days",
        "revised_completion_date",
        "original_completion_date",
        "approval_date",
        "created_at",
        "updated_at",
        "status",
        "eot_date",
        "contract_finish",
        "project_name",
    ]
    ordering = ["project__name", "eot_number"]
    queryset = ProjectEOT.objects.select_related(
        "project",
        "created_by",
        "updated_by",
        "project_dates",
        "project_dates__contractor",
    )

    def get_queryset(self):
        qs = super().get_queryset()
        # Default list hides soft-deleted unless explicitly requested
        show_inactive = str(
            self.request.query_params.get("include_inactive", "")
        ).lower() in ("1", "true", "yes")
        if not show_inactive and self.action in ("list", "by_project"):
            qs = qs.filter(is_active=True)
        return filter_queryset_by_project_access(
            qs, self.request.user, "project__name"
        )

    def _get_eot_or_404(self, pk):
        """Use RBAC-filtered queryset (prevents IDOR via direct pk access)."""
        return self.filter_queryset(self.get_queryset()).get(pk=pk)

    def _success(self, message, data, http_status=status.HTTP_200_OK):
        return Response(
            {"success": True, "message": message, "data": data},
            status=http_status,
        )

    def _error(self, message, errors=None, http_status=status.HTTP_400_BAD_REQUEST):
        body = {"success": False, "message": message}
        if errors is not None:
            body["errors"] = errors
        return Response(body, status=http_status)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        ser = self.get_serializer(page if page is not None else queryset, many=True)
        if page is not None:
            return self.get_paginated_response(
                {
                    "success": True,
                    "message": "EOT list retrieved successfully",
                    "data": ser.data,
                }
            )
        return self._success("EOT list retrieved successfully", ser.data)

    def retrieve(self, request, *args, **kwargs):
        try:
            instance = self._get_eot_or_404(kwargs["pk"])
        except ProjectEOT.DoesNotExist:
            return self._error(
                "EOT record not found", http_status=status.HTTP_404_NOT_FOUND
            )
        return self._success(
            "EOT record retrieved successfully",
            self.get_serializer(instance).data,
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return self._error("Validation failed", errors=serializer.errors)
        try:
            instance = serializer.save()
        except DjangoValidationError as exc:
            return self._error(
                "Validation failed",
                errors=getattr(exc, "message_dict", None)
                or {"non_field_errors": ["Validation failed."]},
            )
        sync_legacy_eot_date(instance.project)
        invalidate_eot_caches()
        write_business_audit(
            entity_type=BusinessAuditLog.ENTITY_EOT,
            action=BusinessAuditLog.ACTION_CREATED,
            actor=request.user,
            entity_id=instance.pk,
            project=instance.project,
            detail=f"EOT #{instance.eot_number} created",
        )
        return self._success(
            "EOT created successfully",
            self.get_serializer(instance).data,
            http_status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        try:
            instance = self._get_eot_or_404(kwargs["pk"])
        except ProjectEOT.DoesNotExist:
            return self._error(
                "EOT record not found", http_status=status.HTTP_404_NOT_FOUND
            )
        if not instance.is_active:
            return self._error("Cannot update an inactive (deleted) EOT.")

        serializer = self.get_serializer(
            instance, data=request.data, partial=partial
        )
        if not serializer.is_valid():
            return self._error("Validation failed", errors=serializer.errors)
        try:
            updated = serializer.save()
        except DjangoValidationError as exc:
            return self._error(
                "Validation failed",
                errors=getattr(exc, "message_dict", None)
                or {"non_field_errors": ["Validation failed."]},
            )
        sync_legacy_eot_date(updated.project)
        invalidate_eot_caches()
        write_business_audit(
            entity_type=BusinessAuditLog.ENTITY_EOT,
            action=BusinessAuditLog.ACTION_UPDATED,
            actor=request.user,
            entity_id=updated.pk,
            project=updated.project,
            detail=f"EOT #{updated.eot_number} updated",
        )
        return self._success(
            "EOT updated successfully",
            self.get_serializer(updated).data,
        )

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        try:
            instance = self._get_eot_or_404(kwargs["pk"])
        except ProjectEOT.DoesNotExist:
            return self._error(
                "EOT record not found", http_status=status.HTTP_404_NOT_FOUND
            )
        if not instance.is_active:
            return self._error("EOT is already inactive.")
        project = instance.project
        eot_number = instance.eot_number
        soft_delete_eot(instance, user=request.user)
        write_business_audit(
            entity_type=BusinessAuditLog.ENTITY_EOT,
            action=BusinessAuditLog.ACTION_DELETED,
            actor=request.user,
            entity_id=instance.pk,
            project=project,
            detail=f"EOT #{eot_number} soft-deleted",
        )
        return self._success(
            f"EOT #{eot_number} for '{project.name}' deleted successfully",
            {},
        )

    @swagger_auto_schema(
        operation_summary="Get pre-signed download / preview URL for EOT supporting document",
        tags=["Project EOT"],
    )
    @action(detail=True, methods=["get"], url_path="download")
    def download(self, request, pk=None):
        try:
            instance = self._get_eot_or_404(pk)
        except ProjectEOT.DoesNotExist:
            return self._error(
                "EOT record not found", http_status=status.HTTP_404_NOT_FOUND
            )
        key = (instance.supporting_document_key or "").strip()
        if not key:
            return self._error(
                "No supporting document attached to this EOT.",
                http_status=status.HTTP_404_NOT_FOUND,
            )
        try:
            from services.s3_eot_documents import generate_presigned_url

            url = generate_presigned_url(key)
        except Exception as exc:
            logger.warning("EOT presign failed; falling back to stored URL: %s", exc)
            url = (instance.supporting_document_url or "").strip() or None
            if not url:
                return self._error(
                    "Unable to generate download URL.",
                    http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
        return self._success(
            "Download URL generated successfully",
            {
                "id": instance.id,
                "file_name": instance.supporting_document_name or None,
                "download_url": url,
                "document_url": instance.supporting_document_url or url,
            },
        )

    @swagger_auto_schema(
        operation_summary="EOT summary for a project",
        responses={200: openapi.Response("OK"), 404: "Project not found"},
        tags=["Project EOT"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"project/(?P<projectName>[^/.]+)",
    )
    def by_project(self, request, projectName=None):
        name = unquote(projectName or "").strip()
        try:
            project = resolve_project_for_module(name)
        except Exception:
            return self._error(
                "Project not found", http_status=status.HTTP_404_NOT_FOUND
            )
        from accounts.rbac_checks import enforce_project_access

        enforce_project_access(request.user, project)
        summary = project_eot_summary(project)
        return self._success("Project EOT summary retrieved successfully", summary)
