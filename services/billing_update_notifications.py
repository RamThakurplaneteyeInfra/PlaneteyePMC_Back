"""
Notify the project Team Leader when a Billing Site Engineer writes financial module data.
"""

from __future__ import annotations

import logging

from django.contrib.auth import get_user_model
from django.db import transaction

from accounts.models import Notification
from accounts.utils import is_billing_site_engineer
from notifications.utils import create_notification_message, send_websocket_notification
from projects.models import Project

logger = logging.getLogger(__name__)
User = get_user_model()

NOTIFICATION_TYPE_BILLING_UPDATE = "BILLING_UPDATE"
TITLE_BILLING_DATA_UPDATED = "Billing Data Updated"


class BillingAction:
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"


class BillingModule:
    CONTRACT_VALUES = "Contract Values"
    INVOICING = "Invoicing Information"
    BG_STATUS = "BG Status"
    PROJECT_DATES = "Project Dates"
    CORRESPONDENCE = "Correspondence & Delivery Status"
    DRAWING_SUMMARY = "Drawing Summary"
    BUDGET_PERFORMANCE = "Budget Performance"
    COST_PERFORMANCE = "Cost Performance"
    CASH_FLOW = "Cash Flow"
    PLANNED_EARNED_VALUE = "Planned vs Actual"
    PLANNED_VS_ACTUAL = "Planned vs Actual"
    CONTRACT_PERFORMANCE = "Contract Performance"


_ACTION_VERBS = {
    BillingAction.CREATE: "created",
    BillingAction.UPDATE: "updated",
    BillingAction.DELETE: "deleted",
}


def _action_verb(action_type: str) -> str:
    return _ACTION_VERBS.get(action_type, "updated")


def build_billing_update_message(
    sender_name: str,
    module_name: str,
    project_name: str,
    action_type: str,
) -> str:
    verb = _action_verb(action_type)
    return (
        f'Billing Site Engineer "{sender_name}" {verb} the '
        f'"{module_name}" for project "{project_name}".'
    )


def _dedupe_key(project_id: int, sender_id: int, module_name: str, action_type: str) -> tuple:
    return (project_id, sender_id, module_name, action_type)


def _pending_notifications():
    connection = transaction.get_connection()
    pending = getattr(connection, "_billing_update_notifications", None)
    if pending is None:
        pending = set()
        connection._billing_update_notifications = pending
    return pending


def notify_team_leader(
    project: Project,
    sender,
    module_name: str,
    action_type: str,
) -> Notification | None:
    """
    Create an in-app alert for the project's Team Leader after a BSE write.

    Returns the Notification instance, or None when no alert is created.
    """
    if not sender or not getattr(sender, "is_authenticated", True):
        return None
    if not is_billing_site_engineer(sender):
        return None
    if not project:
        return None

    team_leader = project.team_lead
    if not team_leader:
        logger.info(
            "Billing update notification skipped — no Team Leader on project %s",
            project.name,
        )
        return None
    if team_leader.id == sender.id:
        return None

    sender_name = sender.get_full_name() or sender.username
    project_name = project.name
    message = build_billing_update_message(
        sender_name, module_name, project_name, action_type
    )

    notification = Notification.objects.create(
        user=team_leader,
        sender=sender,
        project=project,
        module_name=module_name,
        action_type=action_type,
        title=TITLE_BILLING_DATA_UPDATED,
        message=message,
        notification_type=NOTIFICATION_TYPE_BILLING_UPDATE,
        is_read=False,
    )

    ws_message = create_notification_message(
        NOTIFICATION_TYPE_BILLING_UPDATE,
        TITLE_BILLING_DATA_UPDATED,
        message,
        {
            "notification_id": notification.id,
            "project_id": project.id,
            "project_name": project_name,
            "module_name": module_name,
            "action_type": action_type,
            "sender": sender_name,
        },
    )
    send_websocket_notification(team_leader.id, ws_message)

    logger.info(
        "Billing update notification created.\n"
        "Project: %s\nModule: %s\nRecipient: Team Leader (%s)\n"
        "Sender: Billing Site Engineer (%s)\nAction: %s",
        project_name,
        module_name,
        team_leader.username,
        sender.username,
        action_type,
    )
    return notification


def schedule_billing_update_notification(
    sender,
    project: Project | None,
    module_name: str,
    action_type: str,
) -> None:
    """
    Schedule a Team Leader notification after the current DB transaction commits.
    Deduplicates multiple calls with the same project/sender/module/action in one transaction.
    """
    if not sender or not is_billing_site_engineer(sender):
        return
    if not project:
        return

    project_id = project.id
    sender_id = sender.id
    key = _dedupe_key(project_id, sender_id, module_name, action_type)
    pending = _pending_notifications()
    if key in pending:
        return
    pending.add(key)

    def _dispatch():
        pending.discard(key)
        try:
            project_obj = Project.objects.select_related("team_lead").get(pk=project_id)
            sender_obj = User.objects.get(pk=sender_id)
        except (Project.DoesNotExist, User.DoesNotExist):
            logger.warning(
                "Billing update notification skipped — project or sender no longer exists "
                "(project_id=%s, sender_id=%s)",
                project_id,
                sender_id,
            )
            return
        notify_team_leader(project_obj, sender_obj, module_name, action_type)

    transaction.on_commit(_dispatch)


def schedule_billing_update_notification_for_instance(
    sender,
    instance,
    module_name: str,
    action_type: str,
) -> None:
    """Resolve project from a saved model instance and schedule notification."""
    from accounts.rbac import project_from_instance

    schedule_billing_update_notification(
        sender,
        project_from_instance(instance),
        module_name,
        action_type,
    )
