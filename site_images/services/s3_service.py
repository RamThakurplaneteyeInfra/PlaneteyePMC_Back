"""
AWS S3 upload/delete helpers for site progress images.
"""

from __future__ import annotations

import logging
import mimetypes
import uuid

from django.conf import settings
from django.utils.text import slugify

from core.s3_config import get_s3_client, is_boto3_available, is_s3_configured, s3_public_url

from .cloudinary_service import validate_image_file

logger = logging.getLogger(__name__)

CONTENT_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}


def check_s3_ready() -> tuple[bool, str | None]:
    if not is_boto3_available():
        return False, "boto3 is not installed. Run: pip install boto3"
    if not is_s3_configured():
        return False, "AWS S3 configuration missing"
    return True, None


def build_s3_object_key(
    project_name: str,
    year: int,
    month: int,
    filename: str,
) -> str:
    prefix = getattr(settings, "AWS_S3_UPLOAD_PREFIX", "upload").strip("/")
    safe_project = slugify(project_name.strip()) or "project"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
    unique = uuid.uuid4().hex
    return f"{prefix}/{safe_project}/{year}/{month:02d}/{unique}.{ext}"


def _content_type(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in CONTENT_TYPES:
        return CONTENT_TYPES[ext]
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def upload_image(uploaded_file, *, folder: str) -> dict:
    """
    Upload to S3 under the configured prefix.

    ``folder`` is accepted for API compatibility with Cloudinary (unused for key layout).
    """
    ready, message = check_s3_ready()
    if not ready:
        raise RuntimeError(message)

    validate_image_file(uploaded_file)
    file_name = getattr(uploaded_file, "name", "unknown")

    # folder format from image_storage: "{project}/{year}/{month}"
    parts = folder.split("/")
    if len(parts) >= 3:
        project_name, year_str, month_str = parts[0], parts[1], parts[2]
        try:
            object_key = build_s3_object_key(
                project_name,
                int(year_str),
                int(month_str),
                file_name,
            )
        except (TypeError, ValueError):
            object_key = build_s3_object_key(
                folder.replace("/", "-"),
                0,
                0,
                file_name,
            )
    else:
        object_key = build_s3_object_key(folder, 0, 0, file_name)

    bucket = settings.AWS_STORAGE_BUCKET_NAME
    content_type = _content_type(file_name)

    logger.info("S3 upload start: file=%s key=%s bucket=%s", file_name, object_key, bucket)

    uploaded_file.seek(0)
    body = uploaded_file.read()

    client = get_s3_client()
    try:
        client.put_object(
            Bucket=bucket,
            Key=object_key,
            Body=body,
            ContentType=content_type,
        )
    except Exception as exc:
        logger.exception(
            "S3 upload failure: file=%s key=%s error=%s",
            file_name,
            object_key,
            exc,
        )
        raise

    secure_url = s3_public_url(object_key)
    logger.info("S3 upload success: file=%s key=%s", file_name, object_key)

    return {
        "secure_url": secure_url,
        "public_id": object_key,
        "storage_backend": "s3",
    }


def delete_image(object_key: str) -> None:
    if not object_key:
        return

    ready, message = check_s3_ready()
    if not ready:
        logger.warning("S3 delete skipped: %s", message)
        return

    bucket = settings.AWS_STORAGE_BUCKET_NAME
    logger.info("S3 delete start: key=%s bucket=%s", object_key, bucket)

    client = get_s3_client()
    try:
        client.delete_object(Bucket=bucket, Key=object_key)
        logger.info("S3 delete success: key=%s", object_key)
    except Exception as exc:
        logger.exception(
            "S3 delete failure: key=%s error=%s",
            object_key,
            exc,
        )
        raise
