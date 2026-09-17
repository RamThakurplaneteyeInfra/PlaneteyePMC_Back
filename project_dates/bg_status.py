"""BG Status helpers — multi-entry bank guarantee management per project."""

from datetime import date

from django.utils import timezone

from projects.models import Project

from .models import BGStatus, ProjectDates

BG_STATUS_UPDATED = "UPDATED"
BG_STATUS_NOT_UPDATED = "NOT_UPDATED"
BG_STATUS_YET_TO_UPDATE = "YET_TO_UPDATE"

BG_STATUSES = [
    BG_STATUS_UPDATED,
    BG_STATUS_NOT_UPDATED,
    BG_STATUS_YET_TO_UPDATE,
]

EMPTY_BG_SUMMARY = {
    "total_bg": 0,
    "updated": 0,
    "yet_to_update": 0,
    "not_updated": 0,
    "compliance_percentage": 0.0,
}

EMPTY_BG_PAYLOAD = {
    "contractor_bg": [],
    "scl_bg": [],
    "bg_summary": dict(EMPTY_BG_SUMMARY),
}


def _date_to_str(value: date | None) -> str | None:
    return value.isoformat() if value else None


def calculate_bg_status(
    due_date: date | None,
    updated_date: date | None,
    today: date | None = None,
) -> str:
    """
    Calculate BG compliance status from due and updated dates.

    Rules:
      - UPDATED: updated_date is set and updated_date <= due_date
      - YET_TO_UPDATE: updated_date is null and today < due_date
      - NOT_UPDATED: updated_date is null and today > due_date,
        or updated_date is set but updated_date > due_date
    """
    if today is None:
        today = timezone.now().date()

    if due_date is None:
        return BG_STATUS_YET_TO_UPDATE

    if updated_date is not None:
        if updated_date <= due_date:
            return BG_STATUS_UPDATED
        return BG_STATUS_NOT_UPDATED

    if today < due_date:
        return BG_STATUS_YET_TO_UPDATE

    if today > due_date:
        return BG_STATUS_NOT_UPDATED

    return BG_STATUS_NOT_UPDATED


def calculate_bg_summary(
    entries,
    today: date | None = None,
) -> dict:
    """Aggregate compliance counts across BG entries."""
    statuses = [
        calculate_bg_status(entry.due_date, entry.updated_date, today=today)
        for entry in entries
    ]
    total = len(statuses)
    updated = sum(1 for s in statuses if s == BG_STATUS_UPDATED)
    yet_to_update = sum(1 for s in statuses if s == BG_STATUS_YET_TO_UPDATE)
    not_updated = sum(1 for s in statuses if s == BG_STATUS_NOT_UPDATED)
    compliance = round((updated / total) * 100, 2) if total else 0.0

    return {
        "total_bg": total,
        "updated": updated,
        "yet_to_update": yet_to_update,
        "not_updated": not_updated,
        "compliance_percentage": compliance,
    }


def _serialize_bg_entry(entry: BGStatus, today: date | None = None) -> dict:
    return {
        "id": entry.id,
        "bg_type": entry.bg_type,
        "bg_name": entry.bg_name,
        "due_date": _date_to_str(entry.due_date),
        "updated_date": _date_to_str(entry.updated_date),
        "status": calculate_bg_status(entry.due_date, entry.updated_date, today=today),
        "remarks": entry.remarks or "",
    }


def get_bg_entries_for_project(project: Project | None):
    """Return all BG entries for a project with project_date prefetched."""
    if project is None:
        return BGStatus.objects.none()
    return (
        BGStatus.objects.filter(project_date__project_id=project.id)
        .select_related("project_date", "project_date__project")
        .order_by("id")
    )


def bg_status_for_project_date(
    project_date: ProjectDates | None,
    today: date | None = None,
) -> dict:
    """Return BG entries scoped to a single ProjectDates row."""
    if project_date is None:
        return dict(EMPTY_BG_PAYLOAD)

    entries = list(project_date.bg_statuses.all())
    contractor_bg = []
    scl_bg = []

    if project_date.date_type == ProjectDates.DATE_TYPE_SCL:
        scl_bg = [
            _serialize_bg_entry(entry, today=today)
            for entry in entries
            if entry.bg_type == BGStatus.BG_TYPE_SCL
        ]
    else:
        contractor_bg = [
            _serialize_bg_entry(entry, today=today)
            for entry in entries
            if entry.bg_type == BGStatus.BG_TYPE_CONTRACTOR
        ]

    return {
        "contractor_bg": contractor_bg,
        "scl_bg": scl_bg,
        "bg_summary": calculate_bg_summary(entries, today=today),
    }


def bg_status_payload(project: Project | None, today: date | None = None) -> dict:
    """Return project-wide multi-entry BG payload (all contractors + SCL)."""
    if project is None:
        return dict(EMPTY_BG_PAYLOAD)

    entries = list(get_bg_entries_for_project(project))
    contractor_bg = [
        _serialize_bg_entry(entry, today=today)
        for entry in entries
        if entry.bg_type == BGStatus.BG_TYPE_CONTRACTOR
    ]
    scl_bg = [
        _serialize_bg_entry(entry, today=today)
        for entry in entries
        if entry.bg_type == BGStatus.BG_TYPE_SCL
    ]

    return {
        "contractor_bg": contractor_bg,
        "scl_bg": scl_bg,
        "bg_summary": calculate_bg_summary(entries, today=today),
    }


def get_project_date_for_bg(
    project: Project,
    bg_type: str,
    contractor_name: str | None = None,
    contractor_id: int | None = None,
) -> ProjectDates | None:
    """Resolve the ProjectDates row for a BG type (and optional contractor)."""
    if bg_type == ProjectDates.DATE_TYPE_SCL:
        return ProjectDates.objects.filter(
            project_id=project.id,
            date_type=ProjectDates.DATE_TYPE_SCL,
        ).first()

    if contractor_id:
        return ProjectDates.objects.filter(
            project_id=project.id,
            date_type=ProjectDates.DATE_TYPE_CONTRACTOR,
            contractor_id=contractor_id,
        ).first()

    name = (contractor_name or "").strip()
    if not name:
        return ProjectDates.objects.filter(
            project_id=project.id,
            date_type=ProjectDates.DATE_TYPE_CONTRACTOR,
        ).first()

    return ProjectDates.objects.filter(
        project_id=project.id,
        date_type=ProjectDates.DATE_TYPE_CONTRACTOR,
        contractor_name__iexact=name,
    ).first()
