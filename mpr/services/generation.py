"""
MPR generation orchestration.

Flow: MPRService → snapshot_json → PDF/Excel (from snapshot only) → S3.
"""

from __future__ import annotations

import logging
from typing import Any

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from accounts.rbac import RBACDomain
from accounts.rbac_checks import enforce_project_access, enforce_project_write
from core.business_audit import write_business_audit
from core.models import BusinessAuditLog
from projects.models import Project

from mpr.models import MPRReport
from mpr.services.excel_renderer import render_excel
from mpr.services.mpr_executor import submit_mpr_job
from mpr.services.mpr_service import MPRService
from mpr.services.pdf_renderer import render_pdf
from mpr.services.period import MPRPeriod, parse_mpr_month
from mpr.services.s3_mpr import presigned_download_url, upload_mpr_bytes

logger = logging.getLogger("pmc.mpr.generation")


class MPRGenerationError(Exception):
    """Safe client-facing generation error."""


def serialize_mpr_report(report: MPRReport) -> dict[str, Any]:
    user = report.generated_by
    generated_by = None
    if user is not None:
        full_name = ""
        if hasattr(user, "get_full_name"):
            full_name = (user.get_full_name() or "").strip()
        generated_by = {
            "id": user.id,
            "username": getattr(user, "username", None),
            "full_name": full_name or None,
        }
    return {
        "id": report.id,
        "project_id": report.project_id,
        "project_name": getattr(report.project, "name", None),
        "report_month": report.report_month_key,
        "report_year": report.report_year,
        "report_month_number": report.report_month,
        "version": report.version,
        "is_latest": report.is_latest,
        "status": report.status,
        "generated_at": report.generated_at.isoformat() if report.generated_at else None,
        "generation_started_at": (
            report.generation_started_at.isoformat()
            if report.generation_started_at
            else None
        ),
        "generated_by": generated_by,
        "pdf_available": report.pdf_available,
        "excel_available": report.excel_available,
        "error_message": report.error_message or None,
    }


def _next_version(project_id: int, year: int, month: int) -> int:
    current = (
        MPRReport.objects.filter(
            project_id=project_id,
            report_year=year,
            report_month=month,
        ).aggregate(m=Max("version"))["m"]
        or 0
    )
    return int(current) + 1


def _build_snapshot(project: Project, period: MPRPeriod) -> dict:
    # MPRService.build() already validates/normalizes
    return MPRService(project, period).build()


def _mark_previous_not_latest(project_id: int, year: int, month: int) -> None:
    MPRReport.objects.filter(
        project_id=project_id,
        report_year=year,
        report_month=month,
        is_latest=True,
    ).update(is_latest=False, status=MPRReport.STATUS_ARCHIVED)


def create_generating_report(
    *,
    project: Project,
    period: MPRPeriod,
    user,
    snapshot: dict,
    force_new_version: bool = False,
) -> MPRReport:
    """Persist snapshot and mark generating. Caller holds transaction when needed."""
    if force_new_version:
        _mark_previous_not_latest(project.id, period.year, period.month)
        version = _next_version(project.id, period.year, period.month)
    else:
        version = 1

    report = MPRReport.objects.create(
        project=project,
        report_year=period.year,
        report_month=period.month,
        version=version,
        is_latest=True,
        status=MPRReport.STATUS_GENERATING,
        snapshot_json=snapshot,
        generated_by=user if getattr(user, "is_authenticated", False) else None,
        generation_started_at=timezone.now(),
        error_message="",
    )
    write_business_audit(
        entity_type=BusinessAuditLog.ENTITY_MPR,
        action=BusinessAuditLog.ACTION_CREATED,
        actor=user,
        entity_id=report.id,
        project=project,
        detail=f"MPR generation started for {period.month_key} v{version}",
    )
    return report


def run_file_generation(report_id: int) -> None:
    """
    Background worker: render PDF/Excel from snapshot_json and upload.
    Must not query domain tables for MPR metrics — only MPRReport row.
    """
    try:
        report = MPRReport.objects.select_related("project", "generated_by").get(
            pk=report_id
        )
    except MPRReport.DoesNotExist:
        logger.error("MPR report missing id=%s", report_id)
        return

    if report.status not in (
        MPRReport.STATUS_GENERATING,
        MPRReport.STATUS_FAILED,
    ):
        # Allow regenerate worker only when generating
        if report.status != MPRReport.STATUS_GENERATING:
            logger.info(
                "MPR skip generation id=%s status=%s", report_id, report.status
            )
            return

    snapshot = report.snapshot_json
    if not isinstance(snapshot, dict) or not snapshot:
        _fail(report, "MPR snapshot is missing or invalid.")
        return

    try:
        pdf_bytes = render_pdf(
            snapshot,
            meta={
                "version": report.version,
                "letter_date": (
                    report.generated_at.date()
                    if report.generated_at
                    else timezone.localdate()
                ),
                "report_id": report.id,
            },
        )
        excel_bytes = render_excel(snapshot)

        pdf_meta = upload_mpr_bytes(
            content=pdf_bytes,
            project_id=report.project_id,
            year=report.report_year,
            month=report.report_month,
            version=report.version,
            ext=".pdf",
            content_type="application/pdf",
        )
        excel_meta = upload_mpr_bytes(
            content=excel_bytes,
            project_id=report.project_id,
            year=report.report_year,
            month=report.report_month,
            version=report.version,
            ext=".xlsx",
            content_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
        )

        report.pdf_key = pdf_meta["s3_key"]
        report.pdf_url = pdf_meta["url"]
        report.excel_key = excel_meta["s3_key"]
        report.excel_url = excel_meta["url"]
        report.status = MPRReport.STATUS_COMPLETED
        report.generated_at = timezone.now()
        report.error_message = ""
        report.save(
            update_fields=[
                "pdf_key",
                "pdf_url",
                "excel_key",
                "excel_url",
                "status",
                "generated_at",
                "error_message",
                "updated_at",
            ]
        )
        write_business_audit(
            entity_type=BusinessAuditLog.ENTITY_MPR,
            action=BusinessAuditLog.ACTION_COMPLETED,
            actor=report.generated_by,
            entity_id=report.id,
            project=report.project,
            detail=f"MPR files generated for {report.report_month_key} v{report.version}",
        )
        logger.info("MPR generation completed id=%s", report_id)
    except Exception:
        logger.exception("MPR generation failed id=%s", report_id)
        _fail(report, "MPR generation failed.")


def _fail(report: MPRReport, message: str) -> None:
    report.status = MPRReport.STATUS_FAILED
    report.error_message = message[:500]
    report.save(update_fields=["status", "error_message", "updated_at"])
    write_business_audit(
        entity_type=BusinessAuditLog.ENTITY_MPR,
        action=BusinessAuditLog.ACTION_FAILED,
        actor=report.generated_by,
        entity_id=report.id,
        project=getattr(report, "project", None),
        detail=message,
    )


def start_generation(
    *,
    project: Project,
    month: str,
    user,
    regenerate: bool = False,
) -> tuple[MPRReport, bool]:
    """
    Start MPR generation.

    Returns (report, created_new_job).
    - If already generating: return existing, created_new_job=False
    - If completed and not regenerate: return existing, created_new_job=False
    - Else: create snapshot + enqueue job, created_new_job=True
    """
    period = parse_mpr_month(month)
    enforce_project_write(user, project, RBACDomain.GENERAL)

    existing = (
        MPRReport.objects.filter(
            project=project,
            report_year=period.year,
            report_month=period.month,
            is_latest=True,
        )
        .select_related("project", "generated_by")
        .first()
    )

    if existing and existing.status == MPRReport.STATUS_GENERATING:
        return existing, False

    if (
        existing
        and existing.status == MPRReport.STATUS_COMPLETED
        and not regenerate
    ):
        return existing, False

    if existing and existing.status == MPRReport.STATUS_FAILED and not regenerate:
        # Retry failed latest in-place: rebuild snapshot and re-queue
        snapshot = _build_snapshot(project, period)
        existing.snapshot_json = snapshot
        existing.status = MPRReport.STATUS_GENERATING
        existing.generation_started_at = timezone.now()
        existing.error_message = ""
        existing.pdf_key = ""
        existing.pdf_url = ""
        existing.excel_key = ""
        existing.excel_url = ""
        existing.generated_by = user
        existing.save()
        submit_mpr_job(run_file_generation, existing.id)
        existing.refresh_from_db()
        return existing, True

    snapshot = _build_snapshot(project, period)

    with transaction.atomic():
        force_new = bool(existing) or regenerate
        report = create_generating_report(
            project=project,
            period=period,
            user=user,
            snapshot=snapshot,
            force_new_version=force_new,
        )

    submit_mpr_job(run_file_generation, report.id)
    report.refresh_from_db()
    return report, True


def regenerate_report(*, report: MPRReport, user) -> tuple[MPRReport, bool]:
    enforce_project_write(user, report.project, RBACDomain.GENERAL)
    month_key = report.report_month_key
    return start_generation(
        project=report.project,
        month=month_key,
        user=user,
        regenerate=True,
    )


def get_download_url(report: MPRReport, kind: str) -> str | None:
    if report.status != MPRReport.STATUS_COMPLETED:
        return None
    if kind == "pdf":
        key = report.pdf_key
        filename = f"mpr_{report.project_id}_{report.report_month_key}_v{report.version}.pdf"
        url = presigned_download_url(key, filename=filename) if key else None
        return url or (report.pdf_url or None)
    if kind == "excel":
        key = report.excel_key
        filename = f"mpr_{report.project_id}_{report.report_month_key}_v{report.version}.xlsx"
        url = presigned_download_url(key, filename=filename) if key else None
        return url or (report.excel_url or None)
    return None


def assert_can_view_mpr(user, report: MPRReport) -> None:
    enforce_project_access(user, report.project)
