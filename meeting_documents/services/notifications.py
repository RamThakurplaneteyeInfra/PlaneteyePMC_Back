from __future__ import annotations

import logging

from django.contrib.auth import get_user_model
from django.db import transaction

from accounts.models import Notification
from notifications.utils import create_notification_message, send_websocket_notification

logger = logging.getLogger(__name__)
User = get_user_model()

NOTIFICATION_TYPE_MEETING_DOCUMENT = "MEETING_DOCUMENT"
TITLE_MEETING_DOCUMENT_UPLOADED = "Meeting Document Uploaded"


def _recipient_ids(project) -> set[int]:
    ids = set()
    for user in (project.pmc_head, project.team_lead, project.site_engineer):
        if user:
            ids.add(user.id)
    ids.update(project.site_engineers.values_list("id", flat=True))
    ids.update(project.assigned_users.values_list("id", flat=True))
    ids.update(project.coordinators.values_list("id", flat=True))
    return ids


def schedule_meeting_document_upload_notification(document_id: int) -> None:
    def _dispatch():
        from meeting_documents.models import MeetingDocument

        try:
            document = (
                MeetingDocument.objects.select_related(
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
                .get(pk=document_id)
            )
        except MeetingDocument.DoesNotExist:
            return

        sender = document.uploaded_by
        sender_name = (
            sender.get_full_name() or sender.username
            if sender
            else "A user"
        )
        message = (
            f"New {document.meeting_type} uploaded for "
            f"{document.project.name} by {sender_name}."
        )
        recipients = _recipient_ids(document.project)
        if sender:
            recipients.discard(sender.id)

        for user_id in recipients:
            notification = Notification.objects.create(
                user_id=user_id,
                sender=sender,
                project=document.project,
                module_name="Meeting Documents",
                action_type="CREATE",
                title=TITLE_MEETING_DOCUMENT_UPLOADED,
                message=message,
                notification_type=NOTIFICATION_TYPE_MEETING_DOCUMENT,
                is_read=False,
            )
            ws_message = create_notification_message(
                NOTIFICATION_TYPE_MEETING_DOCUMENT,
                TITLE_MEETING_DOCUMENT_UPLOADED,
                message,
                {
                    "notification_id": notification.id,
                    "project_id": document.project_id,
                    "project_name": document.project.name,
                    "document_id": document.id,
                    "meeting_type": document.meeting_type,
                    "sender": sender_name,
                },
            )
            send_websocket_notification(user_id, ws_message)

        logger.info(
            "Meeting document upload notification sent for document %s to %s users",
            document_id,
            len(recipients),
        )

    transaction.on_commit(_dispatch)
