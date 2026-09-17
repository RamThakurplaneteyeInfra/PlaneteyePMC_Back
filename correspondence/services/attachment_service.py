from __future__ import annotations

import logging

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction

from accounts.models import Notification
from accounts.rbac import normalize_project_name, resolve_project
from correspondence.models.attachment import CorrespondenceDocumentAttachment
from correspondence.services.notifications import (
    schedule_correspondence_attachment_notification,
)
from notifications.utils import create_notification_message, send_websocket_notification
from services.s3_correspondence_documents import (
    build_object_key,
    check_s3_ready,
    delete_document,
    optimize_upload,
    upload_document,
)

logger = logging.getLogger(__name__)
User = get_user_model()


def resolve_project_for_correspondence(correspondence):
    return resolve_project(normalize_project_name(correspondence.project_name))


def upload_correspondence_attachment(
    request,
    correspondence,
    *,
    uploaded_file,
    description: str = "",
    document_type: str = "",
    version: int | None = None,
):
    ready, storage_message = check_s3_ready()
    if not ready:
        return None, ("Correspondence document storage is not configured.", storage_message, 503)

    project = resolve_project_for_correspondence(correspondence)
    if project is None:
        return None, ("Project not found.", {"project_name": "Project not found."}, 404)

    uploaded_asset_key = None
    optimized = None
    try:
        optimized = optimize_upload(uploaded_file)
        version = version or CorrespondenceDocumentAttachment.next_version(
            correspondence.id,
            optimized.file_name,
        )
        object_key = build_object_key(
            project_name=project.name,
            correspondence=correspondence,
            filename=optimized.file_name,
            version=version,
        )
        upload_result = upload_document(optimized, object_key=object_key)
        uploaded_asset_key = upload_result["s3_key"]
        with transaction.atomic():
            attachment = CorrespondenceDocumentAttachment.objects.create(
                correspondence=correspondence,
                project=project,
                uploaded_by=request.user,
                file_name=optimized.file_name,
                description=description,
                document_type=document_type,
                document_version=version,
                version_group=CorrespondenceDocumentAttachment.build_version_group(
                    correspondence.id,
                    optimized.file_name,
                ),
                original_file_size=optimized.original_size,
                compressed_file_size=optimized.compressed_size,
                compression_percentage=optimized.compression_percentage,
                content_type=optimized.content_type,
                s3_key=upload_result["s3_key"],
                s3_url=upload_result["s3_url"],
                created_by=request.user,
                updated_by=request.user,
            )
            schedule_correspondence_attachment_notification(attachment.id)
        return attachment, None
    except DjangoValidationError as exc:
        return None, ("Validation failed", exc.messages, 400)
    except Exception as exc:
        if uploaded_asset_key:
            try:
                delete_document(uploaded_asset_key)
            except Exception:
                logger.exception(
                    "Failed to roll back correspondence S3 object %s",
                    uploaded_asset_key,
                )
        logger.exception("Correspondence attachment upload failed: %s", exc)
        return None, ("Failed to upload correspondence attachment.", str(exc), 500)
    finally:
        if optimized is not None:
            try:
                optimized.file_obj.close()
            except Exception:
                pass
