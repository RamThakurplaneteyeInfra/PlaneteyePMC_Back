"""
Project completion workflow — mark completed, audit, notify, invalidate caches.
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


class ProjectCompletionBlocked(Exception):
    def __init__(self, errors: list[dict[str, str]]):
        self.errors = errors
        super().__init__("Project cannot be marked as completed.")


def is_project_completed(project: Project | None) -> bool:
    return bool(project is not None and getattr(project, "status", None) == "completed")


def invalidate_completion_caches() -> None:
    from core.cache_tags import invalidate_tags
    from core.cache_keys import invalidate_list_cache

    invalidate_tags("overview", "dropdown", "projects", "dashboard", "reports", "sites")
    invalidate_list_cache("projects_init_list")


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

    # Avoid notifying the actor twice noise is fine; still include them if in set.
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
                {"project_id": project.id, "project_name": project.name},
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
            f"Project id={project.pk} name={project.name!r} "
            f"status {previous_status!r} → 'completed'. "
            f"notes={notes[:500]!r}"
        ),
        projects=[project],
    )


@transaction.atomic
def complete_project(
    *,
    project: Project,
    actor,
    completion_notes: str = "",
) -> dict[str, Any]:
    project = (
        Project.objects.select_related("team_lead", "completed_by")
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

    # No pending-activity gates — completion is allowed regardless of open DPR/issues/tasks.
    previous = project.status
    notes = (completion_notes or "").strip()
    project.status = "completed"
    project.completed_at = timezone.now()
    project.completed_by = actor if getattr(actor, "is_authenticated", False) else None
    project.completion_notes = notes
    project.save(
        update_fields=[
            "status",
            "completed_at",
            "completed_by",
            "completion_notes",
            "updated_at",
        ]
    )

    _audit_completion(
        actor=actor, project=project, previous_status=previous, notes=notes
    )
    invalidate_completion_caches()
    _notify_project_completed(project, actor)

    logger.info(
        "project_completed id=%s actor=%s",
        project.pk,
        getattr(actor, "username", None),
    )

    completed_by_payload = None
    if project.completed_by_id:
        u = project.completed_by
        full = f"{u.first_name or ''} {u.last_name or ''}".strip()
        completed_by_payload = {
            "id": u.id,
            "username": u.username,
            "full_name": full or u.username,
        }

    return {
        "success": True,
        "message": "Project marked as completed successfully.",
        "data": {
            "project_id": project.id,
            "project_name": project.name,
            "status": project.status,
            "completed_at": project.completed_at.isoformat() if project.completed_at else None,
            "completed_by": completed_by_payload,
            "completion_notes": project.completion_notes,
            "previous_status": previous,
        },
    }
