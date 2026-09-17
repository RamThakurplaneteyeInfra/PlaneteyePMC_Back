from __future__ import annotations

import logging

from django.contrib.auth import get_user_model
from django.db import transaction

from accounts.models import Notification
from notifications.utils import create_notification_message, send_websocket_notification

logger = logging.getLogger(__name__)
User = get_user_model()

NOTIFICATION_TYPE_CORRESPONDENCE_ATTACHMENT = "CORRESPONDENCE_ATTACHMENT"
TITLE_CORRESPONDENCE_ATTACHMENT_UPLOADED = "Correspondence Document Uploaded"


def _recipient_ids(project) -> set[int]:
    ids = set()
    for user in (project.pmc_head, project.team_lead, project.site_engineer):
        if user:
            ids.add(user.id)
    ids.update(project.site_engineers.values_list("id", flat=True))
    ids.update(project.assigned_users.values_list("id", flat=True))
    ids.update(project.coordinators.values_list("id", flat=True))
    if project.billing_site_engineer_id:
        ids.add(project.billing_site_engineer_id)
    return ids


def schedule_correspondence_attachment_notification(attachment_id: int) -> None:
    def _dispatch():
        from correspondence.models.attachment import CorrespondenceDocumentAttachment

        try:
            attachment = (
                CorrespondenceDocumentAttachment.objects.select_related(
                    "correspondence",
                    "project",
                    "uploaded_by",
                    "project__pmc_head",
                    "project__team_lead",
                    "project__site_engineer",
                )
                .prefetch_related(
                    "project__site_engineers",
                    "project__assigned_users",
                    "project__coordinators",
                )
                .get(pk=attachment_id)
            )
        except CorrespondenceDocumentAttachment.DoesNotExist:
            return

        sender = attachment.uploaded_by
        sender_name = (
            sender.get_full_name() or sender.username if sender else "A user"
        )
        message = (
            f"{sender_name} uploaded a correspondence document for "
            f"{attachment.project.name}."
        )
        recipients = _recipient_ids(attachment.project)
        if sender:
            recipients.discard(sender.id)

        for user_id in recipients:
            notification = Notification.objects.create(
                user_id=user_id,
                sender=sender,
                project=attachment.project,
                module_name="Correspondence & Delivery Status",
                action_type=Notification.ACTION_CREATE,
                title=TITLE_CORRESPONDENCE_ATTACHMENT_UPLOADED,
                message=message,
                notification_type=NOTIFICATION_TYPE_CORRESPONDENCE_ATTACHMENT,
                is_read=False,
            )
            ws_message = create_notification_message(
                NOTIFICATION_TYPE_CORRESPONDENCE_ATTACHMENT,
                TITLE_CORRESPONDENCE_ATTACHMENT_UPLOADED,
                message,
                {
                    "notification_id": notification.id,
                    "project_id": attachment.project_id,
                    "project_name": attachment.project.name,
                    "attachment_id": attachment.id,
                    "correspondence_id": attachment.correspondence_id,
                    "sender": sender_name,
                },
            )
            send_websocket_notification(user_id, ws_message)

        logger.info(
            "Correspondence attachment notification sent for attachment %s to %s users",
            attachment_id,
            len(recipients),
        )

    transaction.on_commit(_dispatch)
