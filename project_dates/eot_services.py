"""
EOT helpers: latest completion date, sync legacy eot_date, numbering.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from django.db import transaction
from django.db.models import Max, QuerySet

from core.cache_tags import invalidate_tags

logger = logging.getLogger("pmc.eot")


def active_eots_qs(project) -> QuerySet:
    from project_dates.eot_models import ProjectEOT

    return ProjectEOT.objects.filter(project=project, is_active=True)


def _prefetched_active_eots(project) -> list | None:
    """Return active EOTs from prefetch cache when available (avoids N+1)."""
    cache = getattr(project, "_prefetched_objects_cache", None)
    if cache is None or "eots" not in cache:
        return None
    return [e for e in project.eots.all() if getattr(e, "is_active", True)]


def approved_eots_qs(project) -> QuerySet:
    from project_dates.eot_models import ProjectEOT

    return active_eots_qs(project).filter(status=ProjectEOT.STATUS_APPROVED)


def next_eot_number(project) -> int:
    agg = active_eots_qs(project).aggregate(m=Max("eot_number"))
    return int(agg["m"] or 0) + 1


def latest_approved_eot(project):
    prefetched = _prefetched_active_eots(project)
    if prefetched is not None:
        from project_dates.eot_models import ProjectEOT

        approved = [e for e in prefetched if e.status == ProjectEOT.STATUS_APPROVED]
        if not approved:
            return None
        return max(
            approved,
            key=lambda e: (
                e.eot_number,
                e.revised_completion_date or date.min,
                e.id,
            ),
        )
    return (
        approved_eots_qs(project)
        .select_related("created_by", "updated_by", "project")
        .order_by("-eot_number", "-revised_completion_date", "-id")
        .first()
    )


def current_eot(project):
    """
    Prefer latest approved; else latest active (pending) for display.
    """
    prefetched = _prefetched_active_eots(project)
    if prefetched is not None:
        from project_dates.eot_models import ProjectEOT

        approved = [e for e in prefetched if e.status == ProjectEOT.STATUS_APPROVED]
        pool = approved or prefetched
        if not pool:
            return None
        return max(pool, key=lambda e: (e.eot_number, e.id))

    approved = latest_approved_eot(project)
    if approved:
        return approved
    return (
        active_eots_qs(project)
        .select_related("created_by", "updated_by", "project")
        .order_by("-eot_number", "-id")
        .first()
    )


def original_completion_for_project(project) -> date | None:
    """Baseline contract finish: ProjectDates SCL, else Project.contract_finish."""
    from project_dates.models import ProjectDates

    # Prefer prefetch (list APIs attach SCL rows via Prefetch to_attr / related manager).
    cache = getattr(project, "_prefetched_objects_cache", None)
    if cache is not None and "project_dates" in cache:
        for row in project.project_dates.all():
            if row.date_type == ProjectDates.DATE_TYPE_SCL and row.contract_finish:
                return row.contract_finish
        return project.contract_finish

    scl_attr = getattr(project, "_prefetched_scl_dates", None)
    if scl_attr is not None:
        for row in scl_attr:
            if row.contract_finish:
                return row.contract_finish
        return project.contract_finish

    scl = (
        ProjectDates.objects.filter(
            project=project, date_type=ProjectDates.DATE_TYPE_SCL
        )
        .only("id", "contract_finish")
        .order_by("id")
        .first()
    )
    if scl and scl.contract_finish:
        return scl.contract_finish
    return project.contract_finish


def latest_completion_date(project) -> date | None:
    """
    Latest revised completion from approved EOTs; else original contract finish.
    """
    eot = latest_approved_eot(project)
    if eot and eot.revised_completion_date:
        return eot.revised_completion_date
    return original_completion_for_project(project)


def sync_legacy_eot_date(project) -> None:
    """
    Keep ProjectDates.eot_date = latest approved revised_completion_date
    so existing frontend fields continue to work.
    """
    from project_dates.models import ProjectDates

    latest = latest_approved_eot(project)
    new_date = latest.revised_completion_date if latest else None
    rows = ProjectDates.objects.filter(project=project)
    for row in rows:
        if row.eot_date != new_date:
            ProjectDates.objects.filter(pk=row.pk).update(eot_date=new_date)


def ensure_eot_from_legacy_project_dates(project_dates, *, user=None) -> None:
    """
    When legacy API writes ProjectDates.eot_date, mirror into ProjectEOT history.
    """
    from project_dates.eot_models import ProjectEOT

    if not project_dates or not project_dates.eot_date or not project_dates.project_id:
        return

    project = project_dates.project
    existing = active_eots_qs(project).order_by("-eot_number").first()
    contract = project_dates.contract_finish or project_dates.eot_date
    days = (project_dates.eot_date - contract).days
    if days <= 0:
        days = 1

    if existing and existing.revised_completion_date == project_dates.eot_date:
        return

    if existing and existing.status == ProjectEOT.STATUS_APPROVED:
        existing.revised_completion_date = project_dates.eot_date
        existing.extension_days = days
        existing.original_completion_date = contract
        existing.approval_date = existing.approval_date or project_dates.eot_date
        if user:
            existing.updated_by = user
        existing.save()
        return

    ProjectEOT.objects.create(
        project=project,
        project_dates=project_dates,
        eot_number=next_eot_number(project),
        extension_days=days,
        original_completion_date=contract,
        revised_completion_date=project_dates.eot_date,
        approval_date=project_dates.eot_date,
        reason="Synced from Project Dates eot_date",
        status=ProjectEOT.STATUS_APPROVED,
        created_by=user,
        updated_by=user,
        is_active=True,
    )


def invalidate_eot_caches() -> None:
    invalidate_tags("overview", "projects", "dashboard", "reports")


def project_eot_summary(project) -> dict[str, Any]:
    """Envelope for project details / by-project endpoints (legacy-friendly keys)."""
    from project_dates.eot_serializers import ProjectEOTSerializer

    history_qs = (
        active_eots_qs(project)
        .select_related(
            "created_by",
            "updated_by",
            "project",
            "project_dates",
            "project_dates__contractor",
        )
        .order_by("eot_number")
    )
    current = current_eot(project)
    latest = latest_completion_date(project)
    return {
        "project_name": project.name,
        "project_id": project.id,
        "current_eot": ProjectEOTSerializer(current).data if current else None,
        "eot_count": history_qs.count(),
        # Additive convenience field (does not replace eot_date on current_eot)
        "latest_completion_date": latest.isoformat() if latest else None,
        "eot_history": ProjectEOTSerializer(history_qs, many=True).data,
    }


@transaction.atomic
def soft_delete_eot(eot, *, user=None) -> None:
    # Remove supporting document from S3 when soft-deleting to avoid orphans.
    s3_key = (getattr(eot, "supporting_document_key", None) or "").strip()
    if s3_key:
        try:
            from services.s3_eot_documents import delete_eot_document

            delete_eot_document(s3_key)
        except Exception:
            logger.exception(
                "Failed to delete EOT supporting document eot_id=%s key=%s",
                eot.pk,
                s3_key,
            )
        eot.supporting_document_key = ""
        eot.supporting_document_name = ""
        eot.supporting_document_url = ""

    eot.is_active = False
    update_fields = [
        "is_active",
        "supporting_document_key",
        "supporting_document_name",
        "supporting_document_url",
        "updated_at",
    ]
    if user:
        eot.updated_by = user
        update_fields.append("updated_by")
    eot.save(update_fields=update_fields)
    sync_legacy_eot_date(eot.project)
    invalidate_eot_caches()


def compute_revised_date(original: date, extension_days: int) -> date:
    return original + timedelta(days=int(extension_days))
