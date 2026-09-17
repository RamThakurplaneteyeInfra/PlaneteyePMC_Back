"""Notify PMC Head when new feedback is created — reuses existing infra."""

import logging

from django.contrib.auth import get_user_model

from notifications.utils import create_notification_message, send_websocket_notification

logger = logging.getLogger(__name__)

User = get_user_model()


def _pmc_head_recipients(project):
    """PMC Head users: project's pmc_head plus everyone in the PMC Head group."""
    recipients = {}
    head = getattr(project, "pmc_head", None)
    if head is not None:
        recipients[head.id] = head
    for user in User.objects.filter(groups__name="PMC Head", is_active=True):
        recipients[user.id] = user
    return list(recipients.values())


def notify_feedback_created(feedback):
    """Best-effort real-time notification to PMC Head. Never raises."""
    try:
        project = feedback.project
        recipients = _pmc_head_recipients(project)
        if not recipients:
            logger.info("No PMC Head recipients for feedback %s", feedback.id)
            return

        reporter = feedback.reported_by
        message = create_notification_message(
            "feedback_created",
            f"New Feedback: {feedback.issue_title}",
            (
                f'New {feedback.priority} priority feedback was submitted for '
                f'"{project.name}".'
            ),
            {
                "feedback_id": feedback.id,
                "project_id": project.id,
                "project_name": project.name,
                "priority": feedback.priority,
                "status": feedback.status,
                "reported_by": getattr(reporter, "username", None),
            },
        )
        for user in recipients:
            send_websocket_notification(user.id, message)
        logger.info(
            "Feedback %s created notification dispatched to %d PMC Head recipient(s)",
            feedback.id,
            len(recipients),
        )
    except Exception:
        logger.exception("Failed to send feedback-created notification")
