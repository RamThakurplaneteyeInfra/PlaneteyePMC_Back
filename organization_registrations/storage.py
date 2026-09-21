"""
Persist organization logos without relying on a writable MEDIA_ROOT.

On Vercel / serverless the project filesystem is read-only. Logos must go to S3
(or, in local/dev only, to a writable MEDIA_ROOT). Misconfiguration must raise a
clear error — never an unhandled OSError/PermissionError 500.
"""

from __future__ import annotations

import logging
import os
import tempfile
import uuid
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone
from django.utils.text import get_valid_filename
from rest_framework import serializers

from core.s3_config import (
    DEFAULT_OBJECT_CACHE_CONTROL,
    get_s3_client,
    is_boto3_available,
    is_s3_configured,
    s3_public_url,
)

logger = logging.getLogger(__name__)

MAX_LOGO_BYTES = int(1.5 * 1024 * 1024)

ALLOWED_EXTENSIONS = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}

LOGO_STORAGE_UNAVAILABLE = (
    "Logo storage is unavailable on this server. Configure AWS S3 "
    "(AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_STORAGE_BUCKET_NAME)."
)


class LogoStorageError(Exception):
    """Raised when logo cannot be persisted (misconfigured storage)."""

    def __init__(self, message: str = LOGO_STORAGE_UNAVAILABLE):
        self.message = message
        super().__init__(message)


def logo_root() -> str:
    return (
        str(getattr(settings, "ORGANIZATION_LOGOS_S3_PREFIX", "organization-registrations")).strip("/")
        or "organization-registrations"
    )


def sanitize_filename(filename: str) -> str:
    safe = get_valid_filename(Path(filename or "logo").name)
    return safe or "logo"


def is_serverless_runtime() -> bool:
    """Vercel / AWS Lambda / similar — no persistent local media disk."""
    return bool(
        os.environ.get("VERCEL")
        or os.environ.get("AWS_LAMBDA_FUNCTION_NAME")
        or os.environ.get("LAMBDA_TASK_ROOT")
    )


def media_filesystem_writable() -> bool:
    """True when Django can create files under MEDIA_ROOT (local/dev only)."""
    if is_serverless_runtime():
        return False
    root = Path(getattr(settings, "MEDIA_ROOT", "") or "")
    if not root:
        return False
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / f".write_probe_{uuid.uuid4().hex}"
        probe.write_bytes(b"ok")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def validate_logo(uploaded_file) -> tuple[str, str]:
    """Return (safe_filename, content_type) or raise DRF ValidationError."""
    if uploaded_file is None:
        raise serializers.ValidationError("Organization logo is required.")

    filename = sanitize_filename(getattr(uploaded_file, "name", "logo"))
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise serializers.ValidationError(
            "Logo must be a PNG, JPG, JPEG, WEBP, or SVG file."
        )

    size = int(getattr(uploaded_file, "size", 0) or 0)
    if size <= 0:
        raise serializers.ValidationError("Please upload a non-empty logo file.")
    if size > MAX_LOGO_BYTES:
        raise serializers.ValidationError("Logo must be 1.5 MB or smaller.")

    uploaded_file.seek(0)
    header = uploaded_file.read(256) or b""
    uploaded_file.seek(0)

    if ext in {".jpg", ".jpeg"} and not header.startswith(b"\xff\xd8\xff"):
        raise serializers.ValidationError("Logo must be a PNG, JPG, JPEG, WEBP, or SVG file.")
    if ext == ".png" and not header.startswith(b"\x89PNG\r\n\x1a\n"):
        raise serializers.ValidationError("Logo must be a PNG, JPG, JPEG, WEBP, or SVG file.")
    if ext == ".webp" and not (header[0:4] == b"RIFF" and header[8:12] == b"WEBP"):
        raise serializers.ValidationError("Logo must be a PNG, JPG, JPEG, WEBP, or SVG file.")
    if ext == ".svg":
        snippet = header.lstrip().lower()
        if not (snippet.startswith(b"<svg") or snippet.startswith(b"<?xml")):
            raise serializers.ValidationError(
                "Logo must be a PNG, JPG, JPEG, WEBP, or SVG file."
            )

    return filename, ALLOWED_EXTENSIONS[ext]


def _read_uploaded_bytes(source) -> bytes:
    source.seek(0)
    data = source.read()
    source.seek(0)
    if not data:
        raise LogoStorageError("Please upload a non-empty logo file.")
    return data


def _build_s3_key(ext: str) -> str:
    now = timezone.now()
    return f"{logo_root()}/logos/{now.year}/{now.month:02d}/{uuid.uuid4().hex}{ext}"


def _spooled_from_bytes(data: bytes) -> tempfile.SpooledTemporaryFile:
    buffered = tempfile.SpooledTemporaryFile(max_size=2 * 1024 * 1024, mode="w+b")
    buffered.write(data)
    buffered.seek(0)
    return buffered


def upload_logo_to_s3(uploaded_file, *, original_name: str, content_type: str) -> tuple[str, str]:
    """
    Upload logo bytes to S3. Returns (s3_key, public_url).

    Raises LogoStorageError on any failure.
    """
    if not is_boto3_available() or not is_s3_configured():
        raise LogoStorageError(LOGO_STORAGE_UNAVAILABLE)

    ext = Path(original_name or getattr(uploaded_file, "name", "") or "").suffix.lower() or ".bin"
    s3_key = _build_s3_key(ext)
    data = _read_uploaded_bytes(uploaded_file)
    buffered = _spooled_from_bytes(data)

    try:
        get_s3_client().upload_fileobj(
            buffered,
            settings.AWS_STORAGE_BUCKET_NAME,
            s3_key,
            ExtraArgs={
                "ContentType": content_type or ALLOWED_EXTENSIONS.get(ext, "application/octet-stream"),
                "CacheControl": DEFAULT_OBJECT_CACHE_CONTROL,
                "Metadata": {"original-filename": (original_name or "logo")[:200]},
            },
        )
    except LogoStorageError:
        raise
    except Exception as exc:
        logger.exception("S3 logo upload failed for organization registration")
        raise LogoStorageError(
            "Could not store the organization logo. Please try again later."
        ) from exc
    finally:
        buffered.close()

    return s3_key, s3_public_url(s3_key)


def persist_registration_logo(uploaded_file, *, original_name: str, content_type: str) -> dict:
    """
    Persist logo for a new registration.

    Prefer S3 whenever configured. Fall back to local FileField only when the
    media filesystem is writable (typical local/dev). On serverless, S3 is required.

    Returns dict with keys:
      logo_content: ContentFile | None  (for FileField)
      logo_name: str | None
      logo_s3_key: str
      logo_s3_url: str
    """
    filename = original_name or sanitize_filename(getattr(uploaded_file, "name", "logo"))
    ext = Path(filename).suffix.lower() or ".bin"
    ct = content_type or ALLOWED_EXTENSIONS.get(ext, "application/octet-stream")

    # Prefer S3 when credentials exist (production / Vercel).
    if is_boto3_available() and is_s3_configured():
        s3_key, s3_url = upload_logo_to_s3(
            uploaded_file, original_name=filename, content_type=ct
        )
        return {
            "logo_content": None,
            "logo_name": None,
            "logo_s3_key": s3_key,
            "logo_s3_url": s3_url,
        }

    # Local/dev fallback: write under MEDIA_ROOT only if writable.
    if media_filesystem_writable():
        data = _read_uploaded_bytes(uploaded_file)
        return {
            "logo_content": ContentFile(data),
            "logo_name": filename,
            "logo_s3_key": "",
            "logo_s3_url": "",
        }

    raise LogoStorageError(LOGO_STORAGE_UNAVAILABLE)


def maybe_upload_logo_to_s3(registration) -> None:
    """
    Best-effort S3 copy for rows that already have a local FileField.

    Kept for admin/reprocess paths. Failures are logged and ignored.
    """
    if not registration.logo:
        return
    if registration.logo_s3_key and registration.logo_s3_url:
        return
    if not is_boto3_available() or not is_s3_configured():
        return

    try:
        original = registration.logo_original_name or Path(registration.logo.name).name
        ext = Path(registration.logo.name or "").suffix.lower() or ".bin"
        content_type = ALLOWED_EXTENSIONS.get(ext, "application/octet-stream")
        with registration.logo.open("rb") as source:
            s3_key, s3_url = upload_logo_to_s3(
                source, original_name=original, content_type=content_type
            )
        registration.logo_s3_key = s3_key
        registration.logo_s3_url = s3_url
        registration.save(update_fields=["logo_s3_key", "logo_s3_url"])
    except Exception:
        logger.exception(
            "S3 logo upload failed for organization registration %s; keeping media file",
            getattr(registration, "pk", None),
        )
