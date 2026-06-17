"""BG Status helpers — optional bank guarantee dates per project."""

from datetime import date

from django.utils import timezone

from projects.models import Project

from .models import ProjectBGStatus

BG_STATUS_UPDATED = "UPDATED"
BG_STATUS_NOT_UPDATED = "NOT_UPDATED"
BG_STATUS_YET_TO_UPDATE = "YET_TO_UPDATE"

BG_STATUSES = [
    BG_STATUS_UPDATED,
    BG_STATUS_NOT_UPDATED,
    BG_STATUS_YET_TO_UPDATE,
]

EMPTY_BG_STATUS = {
    "contractor_bg_date": None,
    "contractor_bg_due_date": None,
    "contractor_bg_updated_date": None,
    "contractor_bg_status": BG_STATUS_YET_TO_UPDATE,
    "scl_bg_date": None,
    "scl_bg_due_date": None,
    "scl_bg_updated_date": None,
    "scl_bg_status": BG_STATUS_YET_TO_UPDATE,
}

LEGACY_BG_FIELD_MAP = {
    "contractor_bg_date": "contractor_bg_updated_date",
    "scl_bg_date": "scl_bg_updated_date",
}


def _date_to_str(value: date | None) -> str | None:
    return value.isoformat() if value else None


def calculate_bg_status(
    due_date: date | None,
    updated_date: date | None,
    today: date | None = None,
) -> str:
    """Calculate monthly BG compliance status from due and updated dates."""
    if today is None:
        today = timezone.now().date()

    if updated_date is not None and due_date is not None:
        if updated_date <= due_date:
            return BG_STATUS_UPDATED
        return BG_STATUS_NOT_UPDATED

    if due_date is None:
        return BG_STATUS_YET_TO_UPDATE

    if updated_date is None:
        if due_date >= today:
            return BG_STATUS_YET_TO_UPDATE
        return BG_STATUS_NOT_UPDATED

    return BG_STATUS_NOT_UPDATED


def bg_status_dict(project: Project | None, today: date | None = None) -> dict:
    """Return BG Status payload for a project (null values when unset)."""
    if project is None:
        return dict(EMPTY_BG_STATUS)

    bg = ProjectBGStatus.objects.filter(project_id=project.id).first()
    if bg is None:
        return dict(EMPTY_BG_STATUS)

    return {
        "contractor_bg_date": _date_to_str(bg.contractor_bg_updated_date),
        "contractor_bg_due_date": _date_to_str(bg.contractor_bg_due_date),
        "contractor_bg_updated_date": _date_to_str(bg.contractor_bg_updated_date),
        "contractor_bg_status": calculate_bg_status(
            bg.contractor_bg_due_date,
            bg.contractor_bg_updated_date,
            today=today,
        ),
        "scl_bg_date": _date_to_str(bg.scl_bg_updated_date),
        "scl_bg_due_date": _date_to_str(bg.scl_bg_due_date),
        "scl_bg_updated_date": _date_to_str(bg.scl_bg_updated_date),
        "scl_bg_status": calculate_bg_status(
            bg.scl_bg_due_date,
            bg.scl_bg_updated_date,
            today=today,
        ),
    }


def upsert_bg_status(project: Project, data: dict) -> ProjectBGStatus:
    """Create or partially update BG Status for a project."""
    bg, _ = ProjectBGStatus.objects.get_or_create(project=project)
    updated = False

    for raw_field, model_field in LEGACY_BG_FIELD_MAP.items():
        if raw_field in data:
            setattr(bg, model_field, data[raw_field])
            updated = True

    for field in [
        "contractor_bg_due_date",
        "contractor_bg_updated_date",
        "scl_bg_due_date",
        "scl_bg_updated_date",
    ]:
        if field in data:
            setattr(bg, field, data[field])
            updated = True

    if updated:
        bg.save()
    return bg
