"""
Store organization logos on local media, and on S3 when AWS is configured.

S3 failure must never block saving the registration row.
"""

from __future__ import annotations

import logging
import os
import tempfile
import uuid
from pathlib import Path

from django.conf import settings
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


def logo_root() -> str:
    return (
        str(getattr(settings, "ORGANIZATION_LOGOS_S3_PREFIX", "organization-registrations")).strip("/")
        or "organization-registrations"
    )


def sanitize_filename(filename: str) -> str:
    safe = get_valid_filename(Path(filename or "logo").name)
    return safe or "logo"


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


def _copy_to_spooled_file(source) -> tempfile.SpooledTemporaryFile:
    from core.uploads import copy_file_obj_chunked

    target = tempfile.SpooledTemporaryFile(max_size=2 * 1024 * 1024, mode="w+b")
    copy_file_obj_chunked(source, target)
    return target


def maybe_upload_logo_to_s3(registration) -> None:
    """Best-effort S3 copy. Leaves the local FileField in place on any failure."""
    if not registration.logo:
        return
    if not is_boto3_available() or not is_s3_configured():
        return

    try:
        ext = Path(registration.logo.name or "").suffix.lower() or ".bin"
        now = timezone.now()
        s3_key = (
            f"{logo_root()}/logos/{now.year}/{now.month:02d}/{uuid.uuid4().hex}{ext}"
        )
        content_type = ALLOWED_EXTENSIONS.get(ext, "application/octet-stream")
        original = registration.logo_original_name or Path(registration.logo.name).name

        with registration.logo.open("rb") as source:
            buffered = _copy_to_spooled_file(source)
        try:
            buffered.seek(0, os.SEEK_END)
            size = buffered.tell()
            if size <= 0:
                return
            buffered.seek(0)
            get_s3_client().upload_fileobj(
                buffered,
                settings.AWS_STORAGE_BUCKET_NAME,
                s3_key,
                ExtraArgs={
                    "ContentType": content_type,
                    "CacheControl": DEFAULT_OBJECT_CACHE_CONTROL,
                    "Metadata": {"original-filename": original[:200]},
                },
            )
        finally:
            buffered.close()

        registration.logo_s3_key = s3_key
        registration.logo_s3_url = s3_public_url(s3_key)
        registration.save(update_fields=["logo_s3_key", "logo_s3_url"])
    except Exception:
        logger.exception(
            "S3 logo upload failed for organization registration %s; keeping media file",
            getattr(registration, "pk", None),
        )
