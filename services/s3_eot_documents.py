"""
S3 helpers for Project EOT supporting documents.

Object key layout (prefix from settings.EOT_DOCUMENTS_S3_PREFIX, default ``eot``):
  eot/{project_id}/{year}/{month}/{uuid}{ext}

Public URL example:
  https://pmcproject.s3.ap-south-1.amazonaws.com/eot/...
"""

from __future__ import annotations

import logging
import mimetypes
import tempfile
import uuid
from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.text import get_valid_filename

from core.s3_config import (
    DEFAULT_OBJECT_CACHE_CONTROL,
    get_s3_client,
    is_boto3_available,
    is_s3_configured,
    s3_public_url,
)

logger = logging.getLogger(__name__)

MAX_UPLOAD_SIZE = 100 * 1024 * 1024
PRESIGNED_EXPIRY_SECONDS = 10 * 60

ALLOWED_EXTENSIONS = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}

BLOCKED_EXTENSIONS = {
    ".exe",
    ".bat",
    ".cmd",
    ".com",
    ".msi",
    ".scr",
    ".ps1",
    ".sh",
    ".dll",
    ".js",
    ".vbs",
    ".jar",
}


def eot_root() -> str:
    return (
        str(getattr(settings, "EOT_DOCUMENTS_S3_PREFIX", "eot")).strip("/") or "eot"
    )


def check_s3_ready() -> tuple[bool, str | None]:
    if not is_boto3_available():
        return False, "boto3 is not installed. Run: pip install boto3"
    if not is_s3_configured():
        return False, "AWS S3 configuration missing"
    return True, None


def sanitize_filename(filename: str) -> str:
    safe = get_valid_filename(Path(filename or "document").name)
    return safe or "document"


def extension_for(filename: str) -> str:
    return Path(filename or "").suffix.lower()


def content_type_for(filename: str) -> str:
    ext = extension_for(filename)
    if ext in ALLOWED_EXTENSIONS:
        return ALLOWED_EXTENSIONS[ext]
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def s3_object_url(s3_key: str) -> str:
    """Prefer shared URL builder; fall back to encoded regional URL."""
    try:
        return s3_public_url(s3_key)
    except Exception:
        bucket = settings.AWS_STORAGE_BUCKET_NAME
        region = getattr(settings, "AWS_S3_REGION_NAME", "ap-south-1")
        encoded = quote(s3_key.lstrip("/"), safe="/")
        return f"https://{bucket}.s3.{region}.amazonaws.com/{encoded}"


def validate_upload_file(uploaded_file) -> tuple[str, str]:
    """Returns (safe_filename, content_type)."""
    filename = sanitize_filename(getattr(uploaded_file, "name", "document"))
    ext = extension_for(filename)
    if ext in BLOCKED_EXTENSIONS:
        raise ValidationError("Executable files are not allowed.")
    if ext and ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(
            "Unsupported file type. Allowed: PDF, Word, Excel, JPG, PNG, WEBP."
        )
    size = getattr(uploaded_file, "size", None)
    if size is not None and size > MAX_UPLOAD_SIZE:
        raise ValidationError(
            f"File exceeds maximum size of {MAX_UPLOAD_SIZE // (1024 * 1024)} MB."
        )
    return filename, content_type_for(filename)


def build_object_key(*, project_id: int, year: int, month: int, filename: str) -> str:
    ext = extension_for(filename) or ".pdf"
    return f"{eot_root()}/{int(project_id)}/{int(year)}/{int(month):02d}/{uuid.uuid4().hex}{ext}"


def upload_eot_document(
    *,
    uploaded_file,
    project_id: int,
    year: int | None = None,
    month: int | None = None,
) -> dict:
    """
    Upload supporting document to S3 under the ``eot/`` prefix.

    Returns dict with s3_key, document_url, document_name, content_type, size.
    """
    ready, err = check_s3_ready()
    if not ready:
        raise ValidationError(err or "S3 is not ready.")

    from django.utils import timezone

    now = timezone.now()
    year = int(year or now.year)
    month = int(month or now.month)

    filename, content_type = validate_upload_file(uploaded_file)
    s3_key = build_object_key(
        project_id=project_id, year=year, month=month, filename=filename
    )

    # Buffer to TemporaryFile so large uploads do not stay in memory.
    uploaded_file.seek(0)
    size = 0
    buffered = tempfile.SpooledTemporaryFile(max_size=5 * 1024 * 1024)
    try:
        while True:
            chunk = uploaded_file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_SIZE:
                raise ValidationError(
                    f"File exceeds maximum size of {MAX_UPLOAD_SIZE // (1024 * 1024)} MB."
                )
            buffered.write(chunk)
        if size <= 0:
            raise ValidationError("Uploaded document is empty or unreadable.")

        buffered.seek(0)
        client = get_s3_client()
        bucket = settings.AWS_STORAGE_BUCKET_NAME
        logger.info(
            "EOT S3 upload start project_id=%s key=%s size=%s",
            project_id,
            s3_key,
            size,
        )
        client.upload_fileobj(
            buffered,
            bucket,
            s3_key,
            ExtraArgs={
                "ContentType": content_type,
                "CacheControl": DEFAULT_OBJECT_CACHE_CONTROL,
                "Metadata": {
                    "original-filename": filename[:200],
                    "project-id": str(project_id),
                },
            },
        )
        logger.info("EOT S3 upload success key=%s", s3_key)
    finally:
        try:
            buffered.close()
        except Exception:
            pass

    return {
        "s3_key": s3_key,
        "document_url": s3_object_url(s3_key),
        "document_name": filename,
        "content_type": content_type,
        "size": size,
    }


def delete_eot_document(s3_key: str) -> None:
    if not s3_key:
        return
    # Only delete objects under the eot/ prefix (safety).
    root = eot_root() + "/"
    if not str(s3_key).startswith(root):
        logger.warning("Refusing to delete non-eot key: %s", s3_key)
        return
    ready, message = check_s3_ready()
    if not ready:
        logger.warning("S3 not ready; skip EOT delete for %s (%s)", s3_key, message)
        return
    try:
        get_s3_client().delete_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            Key=s3_key,
        )
        logger.info("EOT S3 delete success key=%s", s3_key)
    except Exception:
        logger.exception("Failed to delete EOT document from S3: %s", s3_key)


def generate_presigned_url(s3_key: str, *, expires_in: int = PRESIGNED_EXPIRY_SECONDS) -> str:
    ready, err = check_s3_ready()
    if not ready:
        raise ValidationError(err or "S3 is not ready.")

    def _sign(key: str, *, expires_in: int) -> str:
        return get_s3_client().generate_presigned_url(
            "get_object",
            Params={
                "Bucket": settings.AWS_STORAGE_BUCKET_NAME,
                "Key": key,
                "ResponseContentDisposition": "inline",
            },
            ExpiresIn=expires_in,
        )

    from services.presigned_url_cache import cached_presigned_url

    return cached_presigned_url(
        cache_namespace="eot_docs",
        s3_key=s3_key,
        expires_in=expires_in,
        generator=_sign,
    )
