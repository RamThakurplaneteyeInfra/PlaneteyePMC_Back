"""MPR Phase 1 preview + Phase 2 generate/history/download APIs."""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.rbac_checks import enforce_project_access
from core.api_errors import error_response
from core.business_audit import write_business_audit
from core.models import BusinessAuditLog
from projects.models import Project

from .models import MPRReport
from .services.cache import (
    build_mpr_cache_key,
    get_cached_mpr,
    set_cached_mpr,
)
from .services.generation import (
    assert_can_view_mpr,
    get_download_url,
    regenerate_report,
    serialize_mpr_report,
    start_generation,
)
from .services.mpr_service import MPRService
from .services.period import InvalidMPRMonth, parse_mpr_month


class MPRPreviewAPIView(APIView):
    """
    GET /api/mpr/projects/{project_id}/preview/?month=YYYY-MM

    Server-side aggregation of all available MPR sections for one project month.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, project_id: int):
        month_raw = request.query_params.get("month")
        try:
            period = parse_mpr_month(month_raw)
        except InvalidMPRMonth as exc:
            return error_response(
                str(exc),
                errors=[{"field": "month", "message": str(exc)}],
                http_status=status.HTTP_400_BAD_REQUEST,
            )

        project = get_object_or_404(
            Project.objects.select_related("team_lead"),
            pk=project_id,
        )
        enforce_project_access(request.user, project)

        cache_key = build_mpr_cache_key(request, project.id, period.month_key)
        cached = get_cached_mpr(cache_key)
        if cached is not None:
            return Response(
                {
                    "success": True,
                    "message": "MPR data retrieved successfully.",
                    "data": cached,
                    "meta": {"cache": "hit"},
                },
                status=status.HTTP_200_OK,
            )

        data = MPRService(project, period).build()
        set_cached_mpr(cache_key, data)

        return Response(
            {
                "success": True,
                "message": "MPR data retrieved successfully.",
                "data": data,
                "meta": {"cache": "miss"},
            },
            status=status.HTTP_200_OK,
        )


class MPRGenerateAPIView(APIView):
    """POST /api/mpr/projects/{project_id}/generate/  body: {month: YYYY-MM}"""

    permission_classes = [IsAuthenticated]

    def post(self, request, project_id: int):
        month_raw = (request.data or {}).get("month")
        try:
            parse_mpr_month(month_raw)
        except InvalidMPRMonth as exc:
            return error_response(
                str(exc),
                errors=[{"field": "month", "message": str(exc)}],
                http_status=status.HTTP_400_BAD_REQUEST,
            )

        project = get_object_or_404(
            Project.objects.select_related("team_lead"),
            pk=project_id,
        )

        try:
            report, created_job = start_generation(
                project=project,
                month=month_raw,
                user=request.user,
                regenerate=False,
            )
        except Exception as exc:
            from rest_framework.exceptions import PermissionDenied

            if isinstance(exc, PermissionDenied):
                raise
            if isinstance(exc, InvalidMPRMonth):
                return error_response(
                    str(exc),
                    errors=[{"field": "month", "message": str(exc)}],
                )
            return error_response(
                "MPR generation failed.",
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        payload = serialize_mpr_report(report)

        if report.status == MPRReport.STATUS_FAILED:
            return error_response(
                report.error_message or "MPR generation failed.",
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if report.status == MPRReport.STATUS_COMPLETED:
            return Response(
                {
                    "success": True,
                    "message": (
                        "MPR generated successfully."
                        if created_job
                        else "MPR already generated."
                    ),
                    "data": payload,
                },
                status=status.HTTP_200_OK,
            )

        return Response(
            {
                "success": True,
                "message": (
                    "MPR generation started."
                    if created_job
                    else "MPR generation already in progress."
                ),
                "data": payload,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class MPRHistoryAPIView(APIView):
    """GET /api/mpr/projects/{project_id}/"""

    permission_classes = [IsAuthenticated]

    def get(self, request, project_id: int):
        project = get_object_or_404(Project, pk=project_id)
        enforce_project_access(request.user, project)

        latest_only = str(request.query_params.get("latest_only", "true")).lower() in {
            "1",
            "true",
            "yes",
        }
        qs = (
            MPRReport.objects.filter(project_id=project_id)
            .select_related("project", "generated_by")
            .order_by("-report_year", "-report_month", "-version")
        )
        if latest_only:
            qs = qs.filter(is_latest=True)

        try:
            page = max(1, int(request.query_params.get("page", 1)))
        except (TypeError, ValueError):
            page = 1
        try:
            page_size = min(100, max(1, int(request.query_params.get("page_size", 20))))
        except (TypeError, ValueError):
            page_size = 20

        total = qs.count()
        start = (page - 1) * page_size
        items = [serialize_mpr_report(r) for r in qs[start : start + page_size]]

        return Response(
            {
                "success": True,
                "message": "MPR history retrieved successfully.",
                "count": total,
                "page": page,
                "page_size": page_size,
                "data": items,
            }
        )


class MPRDetailAPIView(APIView):
    """GET /api/mpr/{id}/"""

    permission_classes = [IsAuthenticated]

    def get(self, request, mpr_id: int):
        report = get_object_or_404(
            MPRReport.objects.select_related("project", "generated_by"),
            pk=mpr_id,
        )
        assert_can_view_mpr(request.user, report)
        return Response(
            {
                "success": True,
                "message": "MPR retrieved successfully.",
                "data": serialize_mpr_report(report),
            }
        )


class MPRRegenerateAPIView(APIView):
    """POST /api/mpr/{id}/regenerate/"""

    permission_classes = [IsAuthenticated]

    def post(self, request, mpr_id: int):
        report = get_object_or_404(
            MPRReport.objects.select_related("project", "generated_by"),
            pk=mpr_id,
        )
        try:
            new_report, created_job = regenerate_report(
                report=report, user=request.user
            )
        except Exception as exc:
            from rest_framework.exceptions import PermissionDenied

            if isinstance(exc, PermissionDenied):
                raise
            return error_response(
                "MPR regeneration failed.",
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        write_business_audit(
            entity_type=BusinessAuditLog.ENTITY_MPR,
            action=BusinessAuditLog.ACTION_UPDATED,
            actor=request.user,
            entity_id=new_report.id,
            project=new_report.project,
            detail=f"MPR regenerate requested from id={report.id}",
        )

        http_status = (
            status.HTTP_202_ACCEPTED if created_job else status.HTTP_200_OK
        )
        return Response(
            {
                "success": True,
                "message": (
                    "MPR regeneration started."
                    if created_job
                    else "MPR generation already in progress."
                ),
                "data": serialize_mpr_report(new_report),
            },
            status=http_status,
        )


class MPRPdfDownloadAPIView(APIView):
    """GET /api/mpr/{id}/pdf/"""

    permission_classes = [IsAuthenticated]

    def get(self, request, mpr_id: int):
        report = get_object_or_404(
            MPRReport.objects.select_related("project"),
            pk=mpr_id,
        )
        assert_can_view_mpr(request.user, report)
        url = get_download_url(report, "pdf")
        if not url:
            return error_response(
                "PDF is not available for this MPR.",
                http_status=status.HTTP_404_NOT_FOUND,
            )
        write_business_audit(
            entity_type=BusinessAuditLog.ENTITY_MPR,
            action=BusinessAuditLog.ACTION_COMPLETED,
            actor=request.user,
            entity_id=report.id,
            project=report.project,
            detail="MPR PDF download URL issued",
        )
        return Response(
            {
                "success": True,
                "message": "PDF download URL generated.",
                "data": {"url": url, "mpr_id": report.id, "format": "pdf"},
            }
        )


class MPRExcelDownloadAPIView(APIView):
    """GET /api/mpr/{id}/excel/"""

    permission_classes = [IsAuthenticated]

    def get(self, request, mpr_id: int):
        report = get_object_or_404(
            MPRReport.objects.select_related("project"),
            pk=mpr_id,
        )
        assert_can_view_mpr(request.user, report)
        url = get_download_url(report, "excel")
        if not url:
            return error_response(
                "Excel is not available for this MPR.",
                http_status=status.HTTP_404_NOT_FOUND,
            )
        write_business_audit(
            entity_type=BusinessAuditLog.ENTITY_MPR,
            action=BusinessAuditLog.ACTION_COMPLETED,
            actor=request.user,
            entity_id=report.id,
            project=report.project,
            detail="MPR Excel download URL issued",
        )
        return Response(
            {
                "success": True,
                "message": "Excel download URL generated.",
                "data": {"url": url, "mpr_id": report.id, "format": "excel"},
            }
        )
