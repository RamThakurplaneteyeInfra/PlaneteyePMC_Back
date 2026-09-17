"""
S3 helpers for Testing Documents.

Object key layout:
  testing/{project_id}/{year}/{month}/{uuid}{ext}

Bucket/region come from existing Django AWS settings (pmcproject / ap-south-1).
"""

from __future__ import annotations

import logging
import mimetypes
import os
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
)

logger = logging.getLogger(__name__)

MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # align with meeting docs / DATA_UPLOAD limit
PRESIGNED_EXPIRY_SECONDS = 10 * 60
TESTING_DOCUMENTS_ROOT = "testing"

ALLOWED_EXTENSIONS = {
    ".pdf": ("application/pdf", "pdf"),
    ".jpg": ("image/jpeg", "image"),
    ".jpeg": ("image/jpeg", "image"),
    ".png": ("image/png", "image"),
    ".webp": ("image/webp", "image"),
    ".mp4": ("video/mp4", "video"),
    ".mov": ("video/quicktime", "video"),
    ".avi": ("video/x-msvideo", "video"),
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


def document_type_for(filename: str, mime_type: str | None = None) -> str:
    ext = extension_for(filename)
    if ext in ALLOWED_EXTENSIONS:
        return ALLOWED_EXTENSIONS[ext][1]
    mime = (mime_type or "").lower()
    if mime == "application/pdf":
        return "pdf"
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    raise ValidationError("Unable to determine document type.")


def content_type_for(filename: str) -> str:
    ext = extension_for(filename)
    if ext in ALLOWED_EXTENSIONS:
        return ALLOWED_EXTENSIONS[ext][0]
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def s3_object_url(s3_key: str) -> str:
    bucket = settings.AWS_STORAGE_BUCKET_NAME
    region = getattr(settings, "AWS_S3_REGION_NAME", "ap-south-1")
    custom_domain = getattr(settings, "AWS_S3_CUSTOM_DOMAIN", "").strip()
    encoded_key = quote(s3_key.lstrip("/"), safe="/")
    if custom_domain:
        return f"https://{custom_domain.rstrip('/')}/{encoded_key}"
    return f"https://{bucket}.s3.{region}.amazonaws.com/{encoded_key}"


def validate_upload_file(uploaded_file) -> tuple[str, str, str]:
    """
    Returns (safe_filename, content_type, document_type).
    """
    filename = sanitize_filename(getattr(uploaded_file, "name", "document"))
    ext = extension_for(filename)
    if ext in BLOCKED_EXTENSIONS:
        raise ValidationError("Executable files are not allowed.")
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(
            "Unsupported file type. Allowed: PDF, JPG, JPEG, PNG, WEBP, MP4, MOV, AVI."
        )

    size = int(getattr(uploaded_file, "size", 0) or 0)
    if size <= 0:
        raise ValidationError("Uploaded file is empty or unreadable.")
    if size > MAX_UPLOAD_SIZE:
        raise ValidationError("File exceeds the configured maximum upload size (100 MB).")

    content_type = ALLOWED_EXTENSIONS[ext][0]
    doc_type = ALLOWED_EXTENSIONS[ext][1]

    # Light magic-byte checks for PDF / common images (videos vary too widely)
    uploaded_file.seek(0)
    header = uploaded_file.read(12) or b""
    uploaded_file.seek(0)
    if ext == ".pdf" and not header.startswith(b"%PDF"):
        raise ValidationError("Invalid PDF file.")
    if ext in {".jpg", ".jpeg"} and not header.startswith(b"\xff\xd8\xff"):
        raise ValidationError("Invalid JPEG file.")
    if ext == ".png" and not header.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValidationError("Invalid PNG file.")
    if ext == ".webp" and not (header[0:4] == b"RIFF" and header[8:12] == b"WEBP"):
        raise ValidationError("Invalid WEBP file.")

    return filename, content_type, doc_type


def build_s3_key(*, project_id: int, year: int, month: int, filename: str) -> str:
    ext = extension_for(filename) or ".bin"
    unique = uuid.uuid4().hex
    return f"{TESTING_DOCUMENTS_ROOT}/{int(project_id)}/{int(year)}/{int(month):02d}/{unique}{ext}"


def _copy_to_spooled_file(source) -> tempfile.SpooledTemporaryFile:
    """Buffer the upload into a fresh, seekable file for boto3.

    Passing Django's request-bound UploadedFile directly to boto3's transfer
    manager can raise "I/O operation on closed file" once the request stream is
    consumed. Copying into an independent spooled temp file avoids that.
    """
    from core.uploads import copy_file_obj_chunked

    target = tempfile.SpooledTemporaryFile(max_size=25 * 1024 * 1024, mode="w+b")
    copy_file_obj_chunked(source, target)
    return target


def _file_size(file_obj) -> int:
    pos = file_obj.tell()
    file_obj.seek(0, os.SEEK_END)
    size = file_obj.tell()
    file_obj.seek(pos)
    return size


def upload_testing_document(
    *,
    uploaded_file,
    project_id: int,
    year: int,
    month: int,
) -> dict:
    ready, err = check_s3_ready()
    if not ready:
        raise ValidationError(err or "S3 is not ready.")

    filename, content_type, doc_type = validate_upload_file(uploaded_file)
    s3_key = build_s3_key(
        project_id=project_id,
        year=year,
        month=month,
        filename=filename,
    )

    buffered = _copy_to_spooled_file(uploaded_file)
    size = _file_size(buffered)
    if size <= 0:
        buffered.close()
        raise ValidationError("Uploaded file is empty or unreadable.")

    client = get_s3_client()
    bucket = settings.AWS_STORAGE_BUCKET_NAME
    try:
        buffered.seek(0)
        client.upload_fileobj(
            buffered,
            bucket,
            s3_key,
            ExtraArgs={
                "ContentType": content_type,
                "CacheControl": DEFAULT_OBJECT_CACHE_CONTROL,
                "Metadata": {
                    "original-filename": filename[:200],
                    "document-type": doc_type,
                },
            },
        )
    finally:
        buffered.close()

    return {
        "s3_key": s3_key,
        "file_url": s3_object_url(s3_key),
        "file_name": filename,
        "file_size": size,
        "mime_type": content_type,
        "document_type": doc_type,
    }


def delete_testing_document(s3_key: str) -> None:
    if not s3_key:
        return
    ready, _ = check_s3_ready()
    if not ready:
        logger.warning("S3 not ready; skip delete for %s", s3_key)
        return
    try:
        get_s3_client().delete_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            Key=s3_key,
        )
    except Exception:
        logger.exception("Failed to delete testing document from S3: %s", s3_key)


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
                # Prefer inline so View / preview opens in-browser.
                "ResponseContentDisposition": "inline",
            },
            ExpiresIn=expires_in,
        )

    try:
        from services.presigned_url_cache import cached_presigned_url

        return cached_presigned_url(
            cache_namespace="testing_docs",
            s3_key=s3_key,
            expires_in=expires_in,
            generator=_sign,
        )
    except Exception:
        logger.debug("Presign cache unavailable; signing directly", exc_info=True)
        return _sign(s3_key, expires_in=expires_in)
