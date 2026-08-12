"""
Due-reminder delivery via existing Alerts (/api/alerts/) + WebSocket.
"""

from __future__ import annotations

import logging
from typing import Any

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import Notification
from notifications.utils import create_notification_message, send_websocket_notification

from .models import Reminder

logger = logging.getLogger("pmc.reminders")

NOTIFICATION_TYPE_REMINDER_DUE = "REMINDER_DUE"
TITLE_REMINDER_DUE = "Reminder Due"


def _due_queryset(*, now=None):
    now = now or timezone.now()
    return (
        Reminder.objects.filter(status=Reminder.STATUS_PENDING, notified_at__isnull=True)
        .filter(
            Q(snoozed_until__isnull=False, snoozed_until__lte=now)
            | Q(snoozed_until__isnull=True, due_at__lte=now)
        )
        .select_related("project", "assigned_to", "created_by")
        .order_by("id")
    )


def notify_reminder_due(reminder: Reminder) -> Notification | None:
    """
    Create an in-app alert + WebSocket push for the assignee.
    Idempotent if notified_at is already set.
    """
    if reminder.status != Reminder.STATUS_PENDING:
        return None
    if reminder.notified_at is not None:
        return None

    assignee = reminder.assigned_to
    if assignee is None:
        return None

    project = reminder.project
    message = (
        f'Reminder "{reminder.title}" is due'
        + (f" for {project.name}" if project_id_safe(project) else "")
        + "."
    )
    if reminder.description:
        message = f"{message} {reminder.description[:200]}"

    notification = Notification.objects.create(
        user=assignee,
        sender=reminder.created_by,
        project=project,
        module_name="Reminders",
        action_type=Notification.ACTION_CREATE,
        title=TITLE_REMINDER_DUE,
        message=message,
        notification_type=NOTIFICATION_TYPE_REMINDER_DUE,
        is_read=False,
    )

    ws = create_notification_message(
        NOTIFICATION_TYPE_REMINDER_DUE,
        TITLE_REMINDER_DUE,
        message,
        {
            "notification_id": notification.id,
            "reminder_id": reminder.id,
            "project_id": project.id if project else None,
            "project_name": project.name if project else "",
            "due_at": reminder.effective_due_at.isoformat()
            if reminder.effective_due_at
            else None,
        },
    )
    try:
        send_websocket_notification(assignee.id, ws)
    except Exception as exc:
        logger.warning(
            "reminder ws failed reminder_id=%s user=%s err=%s",
            reminder.id,
            assignee.id,
            exc,
        )

    reminder.notified_at = timezone.now()
    reminder.save(update_fields=["notified_at", "updated_at"])
    return notification


def project_id_safe(project) -> bool:
    return bool(project is not None and getattr(project, "id", None))


@transaction.atomic
def dispatch_due_reminders(*, limit: int = 500) -> dict[str, Any]:
    """
    Scan pending due reminders and notify assignees.
    Safe to run from Celery, cron, or management command.
    """
    qs = _due_queryset()[: max(1, int(limit))]
    sent = 0
    skipped = 0
    errors = 0
    reminder_ids: list[int] = []

    for reminder in qs:
            try:
                with transaction.atomic():
                    locked = (
                        Reminder.objects.select_for_update()
                        .filter(
                            pk=reminder.pk,
                            status=Reminder.STATUS_PENDING,
                            notified_at__isnull=True,
                        )
                        .first()
                    )
                    if locked is None:
                        skipped += 1
                        continue
                    # Load relations after lock — avoid select_related+FOR UPDATE
                    # outer-join issues with nullable FKs on Postgres.
                    locked = (
                        Reminder.objects.select_related(
                            "project", "assigned_to", "created_by"
                        ).get(pk=locked.pk)
                    )
                    result = notify_reminder_due(locked)
                    if result is None:
                        skipped += 1
                    else:
                        sent += 1
                        reminder_ids.append(locked.id)
            except Exception as exc:
                errors += 1
                logger.exception("dispatch reminder_id=%s failed: %s", reminder.id, exc)

    summary = {
        "scanned": sent + skipped + errors,
        "sent": sent,
        "skipped": skipped,
        "errors": errors,
        "reminder_ids": reminder_ids,
    }
    logger.info("reminders_dispatch %s", summary)
    return summary
