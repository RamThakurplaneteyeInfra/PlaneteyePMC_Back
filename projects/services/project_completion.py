"""
Project completion workflow — mark completed, audit, notify, invalidate caches.

Supports separate physical completion (status=completed) and commercial
billing closure (billing_status=Pending|Completed).
"""

from __future__ import annotations

import logging
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from projects.models import Project

logger = logging.getLogger("pmc.projects.completion")
User = get_user_model()

BILLING_PENDING = Project.BILLING_STATUS_PENDING
BILLING_COMPLETED = Project.BILLING_STATUS_COMPLETED
ALLOWED_BILLING_STATUSES = {BILLING_PENDING, BILLING_COMPLETED}


class ProjectCompletionBlocked(Exception):
    def __init__(self, errors: list[dict[str, str]], message: str | None = None):
        self.errors = errors
        self.message = message or "Project cannot be marked as completed."
        super().__init__(self.message)


class BillingCompletionBlocked(Exception):
    def __init__(self, errors: list[dict[str, str]], message: str | None = None):
        self.errors = errors
        self.message = message or "Billing cannot be marked as completed."
        super().__init__(self.message)


def is_project_completed(project: Project | None) -> bool:
    return bool(project is not None and getattr(project, "status", None) == "completed")


def normalize_billing_status(value: Any) -> str | None:
    """Return canonical Pending/Completed or None if missing/invalid."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered == "pending":
        return BILLING_PENDING
    if lowered == "completed":
        return BILLING_COMPLETED
    return None


def invalidate_completion_caches() -> None:
    from core.cache_tags import invalidate_tags
    from core.cache_keys import invalidate_list_cache

    invalidate_tags("overview", "dropdown", "projects", "dashboard", "reports", "sites")
    invalidate_list_cache("projects_init_list")


def _user_payload(user) -> dict[str, Any] | None:
    if user is None:
        return None
    full = f"{user.first_name or ''} {user.last_name or ''}".strip()
    return {
        "id": user.id,
        "username": user.username,
        "full_name": full or user.username,
    }


def _notify_project_completed(project: Project, actor) -> None:
    from accounts.models import Notification
    from notifications.utils import create_notification_message, send_websocket_notification

    message = f'Project "{project.name}" has been marked as completed.'
    title = f"Project Completed: {project.name}"

    recipient_ids: set[int] = set()
    role_names = ("Head Office", "HO", "CEO", "PMC Head")
    for uid in (
        User.objects.filter(is_active=True, groups__name__in=role_names)
        .values_list("id", flat=True)
        .distinct()
    ):
        recipient_ids.add(uid)
    if project.team_lead_id:
        recipient_ids.add(project.team_lead_id)

    notif_type = getattr(
        Notification,
        "NOTIFICATION_TYPE_PROJECT_COMPLETED",
        "project_completed",
    )

    for uid in recipient_ids:
        try:
            Notification.objects.create(
                user_id=uid,
                sender=actor if getattr(actor, "is_authenticated", False) else None,
                project=project,
                title=title,
                message=message,
                notification_type=notif_type,
                action_type=Notification.ACTION_UPDATE,
                module_name="projects",
            )
            ws = create_notification_message(
                "project_completed",
                title,
                message,
                {
                    "project_id": project.id,
                    "project_name": project.name,
                    "billing_status": project.billing_status,
                },
            )
            send_websocket_notification(uid, ws)
        except Exception as exc:
            logger.warning("completion notify failed user=%s err=%s", uid, exc)


def _audit_completion(*, actor, project: Project, previous_status: str, notes: str) -> None:
    from accounts.models import UserManagementAuditLog
    from accounts.user_management_services import log_user_management_action

    log_user_management_action(
        performed_by=actor,
        target_user=actor,
        action=UserManagementAuditLog.ACTION_STATUS_CHANGED,
        detail=(
            f"Project Completed: id={project.pk} name={project.name!r} "
            f"status {previous_status!r} → 'completed' "
            f"billing_status={project.billing_status!r}. "
            f"notes={notes[:500]!r}"
        ),
        projects=[project],
    )


def _audit_billing_completion(*, actor, project: Project, notes: str) -> None:
    from accounts.models import UserManagementAuditLog
    from accounts.user_management_services import log_user_management_action

    log_user_management_action(
        performed_by=actor,
        target_user=actor,
        action=UserManagementAuditLog.ACTION_STATUS_CHANGED,
        detail=(
            f"Billing Completed: id={project.pk} name={project.name!r} "
            f"billing_status 'Pending' → 'Completed'. "
            f"notes={notes[:500]!r}"
        ),
        projects=[project],
    )


def _completion_response(project: Project, *, previous_status: str | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "project_id": project.id,
        "project_name": project.name,
        "status": project.status,
        "billing_status": project.billing_status,
        "completed_at": project.completed_at.isoformat() if project.completed_at else None,
        "completed_by": _user_payload(project.completed_by),
        "billing_completed_at": (
            project.billing_completed_at.isoformat()
            if project.billing_completed_at
            else None
        ),
        "billing_completed_by": _user_payload(project.billing_completed_by),
        "completion_notes": project.completion_notes,
        "billing_completion_notes": project.billing_completion_notes,
    }
    if previous_status is not None:
        data["previous_status"] = previous_status
    return data


@transaction.atomic
def complete_project(
    *,
    project: Project,
    actor,
    completion_notes: str = "",
    billing_status: Any = None,
    billing_completion_notes: str | None = None,
) -> dict[str, Any]:
    project = (
        Project.objects.select_related(
            "team_lead", "completed_by", "billing_completed_by"
        )
        .filter(pk=project.pk)
        .first()
    )
    if project is None:
        raise Project.DoesNotExist("Project not found")

    if project.status == "merged":
        raise ProjectCompletionBlocked(
            [
                {
                    "field": "status",
                    "message": "Merged projects cannot be marked as completed.",
                }
            ]
        )

    if project.status == "completed":
        raise ProjectCompletionBlocked(
            [
                {
                    "field": "status",
                    "message": "Project is already marked as completed.",
                }
            ]
        )

    normalized = normalize_billing_status(billing_status)
    if normalized is None:
        raise ProjectCompletionBlocked(
            [
                {
                    "field": "billing_status",
                    "message": (
                        "billing_status is required and must be "
                        "'Pending' or 'Completed'."
                    ),
                }
            ],
            message="Invalid billing_status.",
        )

    previous = project.status
    notes = (completion_notes or "").strip()
    now = timezone.now()
    actor_user = actor if getattr(actor, "is_authenticated", False) else None

    project.status = "completed"
    project.completed_at = now
    project.completed_by = actor_user
    project.completion_notes = notes
    project.billing_status = normalized

    update_fields = [
        "status",
        "completed_at",
        "completed_by",
        "completion_notes",
        "billing_status",
        "updated_at",
    ]

    if normalized == BILLING_COMPLETED:
        billing_notes = (
            (billing_completion_notes or "").strip()
            if billing_completion_notes is not None
            else ""
        )
        project.billing_completed_at = now
        project.billing_completed_by = actor_user
        project.billing_completion_notes = billing_notes or None
        update_fields.extend(
            [
                "billing_completed_at",
                "billing_completed_by",
                "billing_completion_notes",
            ]
        )
    else:
        project.billing_completed_at = None
        project.billing_completed_by = None
        project.billing_completion_notes = None
        update_fields.extend(
            [
                "billing_completed_at",
                "billing_completed_by",
                "billing_completion_notes",
            ]
        )

    project.save(update_fields=update_fields)

    _audit_completion(
        actor=actor, project=project, previous_status=previous, notes=notes
    )
    if normalized == BILLING_COMPLETED:
        _audit_billing_completion(
            actor=actor,
            project=project,
            notes=project.billing_completion_notes or notes,
        )

    invalidate_completion_caches()
    _notify_project_completed(project, actor)

    logger.info(
        "project_completed id=%s actor=%s billing_status=%s",
        project.pk,
        getattr(actor, "username", None),
        project.billing_status,
    )

    return {
        "success": True,
        "message": "Project marked as completed successfully.",
        "data": _completion_response(project, previous_status=previous),
    }


@transaction.atomic
def complete_billing(
    *,
    project: Project,
    actor,
    billing_completion_notes: str = "",
) -> dict[str, Any]:
    project = (
        Project.objects.select_related(
            "team_lead", "completed_by", "billing_completed_by"
        )
        .filter(pk=project.pk)
        .first()
    )
    if project is None:
        raise Project.DoesNotExist("Project not found")

    if project.status != "completed":
        raise BillingCompletionBlocked(
            [
                {
                    "field": "status",
                    "message": (
                        "Billing can only be marked completed after the "
                        "project is marked as completed."
                    ),
                }
            ],
            message=(
                "Billing cannot be marked completed unless the project "
                "status is Completed."
            ),
        )

    if project.billing_status == BILLING_COMPLETED:
        raise BillingCompletionBlocked(
            [
                {
                    "field": "billing_status",
                    "message": "Billing is already marked as completed.",
                }
            ]
        )

    notes = (billing_completion_notes or "").strip()
    actor_user = actor if getattr(actor, "is_authenticated", False) else None
    project.billing_status = BILLING_COMPLETED
    project.billing_completed_at = timezone.now()
    project.billing_completed_by = actor_user
    project.billing_completion_notes = notes or None
    project.save(
        update_fields=[
            "billing_status",
            "billing_completed_at",
            "billing_completed_by",
            "billing_completion_notes",
            "updated_at",
        ]
    )

    _audit_billing_completion(actor=actor, project=project, notes=notes)
    invalidate_completion_caches()

    logger.info(
        "billing_completed id=%s actor=%s",
        project.pk,
        getattr(actor, "username", None),
    )

    return {
        "success": True,
        "message": "Billing marked as completed successfully.",
        "data": {
            "project_id": project.id,
            "project_name": project.name,
            "status": project.status,
            "billing_status": project.billing_status,
            "billing_completed_at": (
                project.billing_completed_at.isoformat()
                if project.billing_completed_at
                else None
            ),
            "billing_completed_by": _user_payload(project.billing_completed_by),
            "billing_completion_notes": project.billing_completion_notes,
        },
    }
