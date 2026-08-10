"""
Single source of truth for Tutorial Video sidebar sections.

Store stable keys in the DB; expose display names via section_name.
"""

from __future__ import annotations

TUTORIAL_SECTIONS: dict[str, str] = {
    "overview": "Overview",
    "projects": "Projects",
    "initialize_project": "Initialize Project",
    "user_management": "User Management",
    "site_progress": "Site Progress",
    "site_photos": "Site Photos",
    "testing_photos": "Testing Photos",
    "project_feedback": "Project Feedback",
    "portfolio": "Portfolio",
    "dpr_review": "DPR Review",
    "wpr_review": "WPR Review",
    "meeting_documents": "Meeting Documents",
    "alerts": "Alerts",
}

TUTORIAL_SECTION_CHOICES = [(key, label) for key, label in TUTORIAL_SECTIONS.items()]


def normalize_section(value: str | None) -> str | None:
    """Return canonical section key, or None if empty."""
    if value is None:
        return None
    key = str(value).strip().lower()
    return key or None


def is_valid_section(value: str | None) -> bool:
    key = normalize_section(value)
    return bool(key and key in TUTORIAL_SECTIONS)


def section_display_name(value: str | None) -> str:
    key = normalize_section(value) or ""
    return TUTORIAL_SECTIONS.get(key, "")


def validate_section_or_error(value: str | None) -> str:
    """
    Normalize and validate a section key.
    Raises ValueError with a safe message when invalid/missing.
    """
    key = normalize_section(value)
    if not key:
        raise ValueError("This field is required.")
    if key not in TUTORIAL_SECTIONS:
        raise ValueError("Invalid tutorial section.")
    return key
