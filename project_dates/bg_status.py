"""BG Status helpers — optional bank guarantee dates per project."""

from projects.models import Project

from .models import ProjectBGStatus

EMPTY_BG_STATUS = {
    "contractor_bg_date": None,
    "scl_bg_date": None,
}


def bg_status_dict(project: Project | None) -> dict:
    """Return BG Status payload for a project (null dates when unset)."""
    if project is None:
        return dict(EMPTY_BG_STATUS)

    bg = ProjectBGStatus.objects.filter(project_id=project.id).first()
    if bg is None:
        return dict(EMPTY_BG_STATUS)

    return {
        "contractor_bg_date": (
            bg.contractor_bg_date.isoformat() if bg.contractor_bg_date else None
        ),
        "scl_bg_date": bg.scl_bg_date.isoformat() if bg.scl_bg_date else None,
    }


def upsert_bg_status(project: Project, data: dict) -> ProjectBGStatus:
    """Create or partially update BG Status for a project."""
    bg, _ = ProjectBGStatus.objects.get_or_create(project=project)
    updated = False

    if "contractor_bg_date" in data:
        bg.contractor_bg_date = data["contractor_bg_date"]
        updated = True
    if "scl_bg_date" in data:
        bg.scl_bg_date = data["scl_bg_date"]
        updated = True

    if updated:
        bg.save()
    return bg
