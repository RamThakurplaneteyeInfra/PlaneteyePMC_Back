from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from urllib.parse import quote

from django.conf import settings

from core.s3_config import (
    DEFAULT_OBJECT_CACHE_CONTROL,
    get_s3_client,
    is_boto3_available,
    is_s3_configured,
)
from services.s3_meeting_documents import (
    CompressedDocument,
    check_s3_ready,
    compress_document,
    extension_for,
    sanitize_filename,
    sanitize_key_segment,
)

logger = logging.getLogger(__name__)

PRESIGNED_EXPIRY_SECONDS = 10 * 60
CORRESPONDENCE_ROOT = "Correspondence"


def s3_correspondence_document_url(s3_key: str) -> str:
    bucket = settings.AWS_STORAGE_BUCKET_NAME
    region = getattr(settings, "AWS_S3_REGION_NAME", "ap-south-1")
    custom_domain = getattr(settings, "AWS_S3_CUSTOM_DOMAIN", "").strip()
    encoded_key = quote(s3_key.lstrip("/"), safe="/")
    if custom_domain:
        return f"https://{custom_domain.rstrip('/')}/{encoded_key}"
    return f"https://{bucket}.s3.{region}.amazonaws.com/{encoded_key}"


def correspondence_storage_folder(correspondence) -> str:
    from correspondence.models.correspondence import CorrespondenceDocument

    if correspondence.flow_direction == CorrespondenceDocument.FLOW_OUTBOUND_SCL:
        return "SCL"
    if correspondence.correspondence_type == CorrespondenceDocument.TYPE_CONTRACTOR:
        return "CONTRACTOR"
    return "CLIENT"


def build_s3_key(
    *,
    project_name: str,
    correspondence,
    filename: str,
    version: int | None = None,
) -> str:
    safe_project = sanitize_key_segment(project_name, default="Project")
    folder_type = correspondence_storage_folder(correspondence)
    safe_name = sanitize_filename(filename)
    stem = Path(safe_name).stem
    stem = re.sub(r"_v\d+$", "", stem)
    stem = stem[:90] or "document"
    ext = extension_for(safe_name) or ".bin"
    version_suffix = f"_v{version}" if version is not None else "_v1"
    meeting_date = correspondence.received_date
    base_key = (
        f"{CORRESPONDENCE_ROOT}/{safe_project}/{folder_type}/"
        f"{meeting_date.year}/{meeting_date.month:02d}/{stem}{version_suffix}{ext}"
    )

    try:
        from correspondence.models.attachment import CorrespondenceDocumentAttachment

        if CorrespondenceDocumentAttachment.objects.filter(s3_key=base_key).exists():
            counter = 1
            while True:
                candidate_key = (
                    f"{CORRESPONDENCE_ROOT}/{safe_project}/{folder_type}/"
                    f"{meeting_date.year}/{meeting_date.month:02d}/"
                    f"{stem}{version_suffix}_{counter}{ext}"
                )
                if not CorrespondenceDocumentAttachment.objects.filter(
                    s3_key=candidate_key
                ).exists():
                    return candidate_key
                counter += 1
    except Exception:
        unique = uuid.uuid4().hex[:8]
        return (
            f"{CORRESPONDENCE_ROOT}/{safe_project}/{folder_type}/"
            f"{meeting_date.year}/{meeting_date.month:02d}/"
            f"{stem}{version_suffix}_{unique}{ext}"
        )

    return base_key


def upload_correspondence_document(
    compressed: CompressedDocument,
    *,
    s3_key: str | None = None,
    object_key: str | None = None,
) -> dict:
    key = s3_key or object_key
    if not key:
        raise ValueError("s3_key is required for upload.")
    ready, message = check_s3_ready()
    if not ready:
        raise RuntimeError(message)

    logger.info("Correspondence attachment S3 upload start: key=%s", key)
    compressed.file_obj.seek(0)
    get_s3_client().upload_fileobj(
        compressed.file_obj,
        settings.AWS_STORAGE_BUCKET_NAME,
        key,
        ExtraArgs={
            "ContentType": compressed.content_type,
            "CacheControl": DEFAULT_OBJECT_CACHE_CONTROL,
            "Metadata": {"original-filename": compressed.file_name},
        },
    )
    logger.info("Correspondence attachment S3 upload success: key=%s", key)
    return {"s3_key": key, "s3_url": s3_correspondence_document_url(key)}


def delete_correspondence_document(s3_key: str) -> None:
    if not s3_key:
        return
    ready, message = check_s3_ready()
    if not ready:
        logger.warning("Correspondence attachment S3 delete skipped: %s", message)
        return
    logger.info("Correspondence attachment S3 delete start: key=%s", s3_key)
    get_s3_client().delete_object(
        Bucket=settings.AWS_STORAGE_BUCKET_NAME,
        Key=s3_key,
    )
    logger.info("Correspondence attachment S3 delete success: key=%s", s3_key)


def generate_presigned_url(
    s3_key: str,
    *,
    expires_in: int = PRESIGNED_EXPIRY_SECONDS,
) -> str:
    from services.presigned_url_cache import cached_presigned_url

    def _sign(key: str, *, expires_in: int) -> str:
        ready, message = check_s3_ready()
        if not ready:
            raise RuntimeError(message)
        logger.info("Correspondence attachment presigned URL generated: key=%s", key)
        return get_s3_client().generate_presigned_url(
            "get_object",
            Params={
                "Bucket": settings.AWS_STORAGE_BUCKET_NAME,
                "Key": key,
                "ResponseContentDisposition": "inline",
            },
            ExpiresIn=expires_in,
        )

    return cached_presigned_url(
        cache_namespace="correspondence",
        s3_key=s3_key,
        expires_in=expires_in,
        generator=_sign,
    )


optimize_upload = compress_document
upload_document = upload_correspondence_document
delete_document = delete_correspondence_document
generate_presigned_download_url = generate_presigned_url
build_object_key = build_s3_key
