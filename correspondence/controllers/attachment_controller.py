from __future__ import annotations

import logging

from drf_yasg.utils import swagger_auto_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from correspondence.models.attachment import CorrespondenceDocumentAttachment
from correspondence.permissions import (
    CorrespondenceAttachmentPermission,
    can_delete_correspondence_attachment,
    can_upload_correspondence_attachment,
    can_view_correspondence_attachment,
)
from correspondence.services.attachment_service import upload_correspondence_attachment
from services.s3_correspondence_documents import (
    delete_document,
    generate_presigned_download_url,
)

from .attachment_serializer import (
    CorrespondenceAttachmentDetailSerializer,
    CorrespondenceAttachmentPatchSerializer,
    CorrespondenceAttachmentSerializer,
)
from .correspondence_controller import _flatten_errors

logger = logging.getLogger(__name__)


class CorrespondenceAttachmentViewSet(viewsets.GenericViewSet):
    queryset = CorrespondenceDocumentAttachment.objects.select_related(
        "correspondence",
        "project",
        "uploaded_by",
        "created_by",
        "updated_by",
    )
    permission_classes = [CorrespondenceAttachmentPermission]
    parser_classes = [MultiPartParser, FormParser]
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def _success(self, message, data, http_status=status.HTTP_200_OK):
        return Response(
            {"success": True, "message": message, "data": data},
            status=http_status,
        )

    def _error(self, message, errors=None, http_status=status.HTTP_400_BAD_REQUEST):
        payload = {"success": False, "message": message}
        if errors is not None:
            payload["errors"] = errors
        return Response(payload, status=http_status)

    def get_object(self):
        return self.get_queryset().get(pk=self.kwargs["pk"], is_active=True)

    @swagger_auto_schema(tags=["Correspondence Attachments"])
    def partial_update(self, request, pk=None):
        try:
            attachment = self.get_object()
        except CorrespondenceDocumentAttachment.DoesNotExist:
            return self._error(
                "Correspondence attachment not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        if not can_upload_correspondence_attachment(request.user, attachment.correspondence):
            return self._error(
                "You do not have permission to update correspondence attachments.",
                http_status=status.HTTP_403_FORBIDDEN,
            )

        serializer = CorrespondenceAttachmentPatchSerializer(
            data=request.data,
            partial=True,
        )
        if not serializer.is_valid():
            return self._error(
                "Validation failed",
                errors=_flatten_errors(serializer.errors),
            )
        data = serializer.validated_data

        if "file" in data:
            version = CorrespondenceDocumentAttachment.next_version(
                attachment.correspondence_id,
                data["file"].name,
            )
            new_attachment, error = upload_correspondence_attachment(
                request,
                attachment.correspondence,
                uploaded_file=data["file"],
                description=data.get("description", attachment.description),
                document_type=data.get("document_type", attachment.document_type),
                version=version,
            )
            if error:
                message, errors, code = error
                return self._error(message, errors=errors, http_status=code)
            new_attachment._download_url = generate_presigned_download_url(
                new_attachment.s3_key
            )
            new_attachment._download_url_expires_in_seconds = 600
            return self._success(
                "New attachment version uploaded successfully.",
                CorrespondenceAttachmentDetailSerializer(new_attachment).data,
                http_status=status.HTTP_201_CREATED,
            )

        for field in ("description", "document_type"):
            if field in data:
                setattr(attachment, field, data[field])
        attachment.updated_by = request.user
        attachment.save(
            update_fields=["description", "document_type", "updated_by", "updated_at"]
        )
        return self._success(
            "Attachment updated successfully.",
            CorrespondenceAttachmentSerializer(attachment).data,
        )

    update = partial_update

    @swagger_auto_schema(tags=["Correspondence Attachments"])
    def destroy(self, request, pk=None):
        try:
            attachment = self.get_object()
        except CorrespondenceDocumentAttachment.DoesNotExist:
            return self._error(
                "Correspondence attachment not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        if not can_delete_correspondence_attachment(request.user, attachment):
            return self._error(
                "You do not have permission to delete correspondence attachments.",
                http_status=status.HTTP_403_FORBIDDEN,
            )

        try:
            delete_document(attachment.s3_key)
        except Exception as exc:
            logger.exception("Correspondence attachment S3 delete failed: %s", exc)
            return self._error(
                "Failed to delete attachment from storage.",
                errors=str(exc),
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        attachment.delete()
        return self._success("Attachment deleted successfully.", {})

    @action(detail=True, methods=["get"], url_path="download")
    def download(self, request, pk=None):
        try:
            attachment = self.get_object()
        except CorrespondenceDocumentAttachment.DoesNotExist:
            return self._error(
                "Correspondence attachment not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        if not can_view_correspondence_attachment(request.user, attachment.correspondence):
            return self._error(
                "You do not have permission to download correspondence attachments.",
                http_status=status.HTTP_403_FORBIDDEN,
            )

        try:
            url = generate_presigned_download_url(attachment.s3_key)
        except RuntimeError as exc:
            return self._error(
                "Unable to generate download URL.",
                errors=str(exc),
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return self._success(
            "Download URL generated successfully.",
            {
                "id": attachment.id,
                "correspondence_id": attachment.correspondence_id,
                "file_name": attachment.file_name,
                "download_url": url,
                "expires_in_seconds": 600,
            },
        )
