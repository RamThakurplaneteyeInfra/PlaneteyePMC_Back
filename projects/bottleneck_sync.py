"""
Sync bottleneck dashboard JSON (project-logs left_text) with Bottleneck records.
"""

import json
import logging
from datetime import datetime

from django.contrib.auth import get_user_model
from django.db import transaction

from bottlenecks.models import Bottleneck

logger = logging.getLogger(__name__)
User = get_user_model()

_TYPE_ALIASES = {
    "issue": Bottleneck.TYPE_ISSUE,
    "concern": Bottleneck.TYPE_CONCERN,
    "risk": Bottleneck.TYPE_RISK,
    "action": Bottleneck.TYPE_ACTION,
}

_PRIORITY_ALIASES = {
    "low": Bottleneck.PRIORITY_LOW,
    "medium": Bottleneck.PRIORITY_MEDIUM,
    "high": Bottleneck.PRIORITY_HIGH,
    "critical": Bottleneck.PRIORITY_CRITICAL,
}

_STATUS_ALIASES = {
    "open": Bottleneck.STATUS_OPEN,
    "in progress": Bottleneck.STATUS_IN_PROGRESS,
    "in_progress": Bottleneck.STATUS_IN_PROGRESS,
    "closed": Bottleneck.STATUS_CLOSED,
}

_PRIORITY_DISPLAY = {
    Bottleneck.PRIORITY_LOW: "Low",
    Bottleneck.PRIORITY_MEDIUM: "Medium",
    Bottleneck.PRIORITY_HIGH: "High",
    Bottleneck.PRIORITY_CRITICAL: "Critical",
}

_STATUS_DISPLAY = {
    Bottleneck.STATUS_OPEN: "Open",
    Bottleneck.STATUS_IN_PROGRESS: "In Progress",
    Bottleneck.STATUS_CLOSED: "Closed",
}


def _normalize_type(value) -> str:
    if not value:
        return Bottleneck.TYPE_ISSUE
    key = str(value).strip().upper().replace(" ", "_")
    if key in {c[0] for c in Bottleneck.TYPE_CHOICES}:
        return key
    return _TYPE_ALIASES.get(str(value).strip().lower(), Bottleneck.TYPE_ISSUE)


def _normalize_priority(value) -> str:
    if not value:
        return Bottleneck.PRIORITY_MEDIUM
    key = str(value).strip().upper()
    if key in {c[0] for c in Bottleneck.PRIORITY_CHOICES}:
        return key
    return _PRIORITY_ALIASES.get(str(value).strip().lower(), Bottleneck.PRIORITY_MEDIUM)


def _normalize_status(value) -> str:
    if not value:
        return Bottleneck.STATUS_OPEN
    key = str(value).strip().upper().replace(" ", "_")
    if key in {c[0] for c in Bottleneck.STATUS_CHOICES}:
        return key
    return _STATUS_ALIASES.get(str(value).strip().lower(), Bottleneck.STATUS_OPEN)


def _parse_target_date(value):
    if not value:
        return None
    if isinstance(value, str) and value.strip():
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").date()
        except ValueError:
            return None
    return value


def _resolve_assigned_to(raw):
    if raw in (None, "", "null"):
        return None
    try:
        user_id = int(raw)
    except (TypeError, ValueError):
        return None
    return User.objects.filter(pk=user_id, is_active=True).first()


def parse_dashboard_items(left_text: str) -> list[dict]:
    """Parse left_text JSON from bottleneck_dashboard entry."""
    if not left_text or not str(left_text).strip():
        return []
    try:
        data = json.loads(left_text)
    except json.JSONDecodeError as exc:
        logger.warning("Invalid bottleneck dashboard JSON: %s", exc)
        return []
    if isinstance(data, dict):
        data = data.get("items") or data.get("bottlenecks") or [data]
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def item_to_dashboard_dict(bottleneck: Bottleneck) -> dict:
    """Serialize Bottleneck for frontend left_text JSON."""
    assigned = ""
    if bottleneck.assigned_to_id:
        assigned = str(bottleneck.assigned_to_id)

    return {
        "id": bottleneck.client_id or str(bottleneck.pk),
        "type": bottleneck.type,
        "description": bottleneck.description,
        "priority": _PRIORITY_DISPLAY.get(
            bottleneck.priority, bottleneck.priority.title()
        ),
        "status": _STATUS_DISPLAY.get(bottleneck.status, bottleneck.status),
        "assignedTo": assigned,
        "targetDate": bottleneck.target_date.isoformat() if bottleneck.target_date else "",
        "remarks": bottleneck.remarks or "",
    }


def bottlenecks_to_left_text(project_id: int) -> str:
    items = [
        item_to_dashboard_dict(bn)
        for bn in Bottleneck.objects.filter(project_id=project_id).order_by("created_at")
    ]
    return json.dumps(items)


@transaction.atomic
def sync_bottlenecks_from_dashboard(project_id: int, left_text: str, user=None) -> str:
    """
    Replace project bottlenecks from dashboard JSON. Returns normalized left_text.
    """
    items = parse_dashboard_items(left_text)
    Bottleneck.objects.filter(project_id=project_id).delete()

    for item in items:
        client_id = str(item.get("id") or item.get("client_id") or "").strip() or None
        Bottleneck.objects.create(
            project_id=project_id,
            client_id=client_id,
            type=_normalize_type(item.get("type")),
            description=(item.get("description") or "").strip() or "—",
            priority=_normalize_priority(item.get("priority")),
            status=_normalize_status(item.get("status")),
            assigned_to=_resolve_assigned_to(
                item.get("assigned_to") or item.get("assignedTo")
            ),
            target_date=_parse_target_date(
                item.get("target_date") or item.get("targetDate")
            ),
            remarks=(item.get("remarks") or "").strip(),
            created_by=user,
            updated_by=user,
        )

    return bottlenecks_to_left_text(project_id)
