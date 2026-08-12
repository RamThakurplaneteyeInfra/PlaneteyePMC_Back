"""
S3 helpers for Drawing Register file attachments.

Object key layout:
  Drawing/{project_id}/{register_id}/rev-{revision}/{uuid}{ext}

Uses configured AWS settings (no hardcoded credentials).
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
    s3_public_url,
)

logger = logging.getLogger(__name__)

PRESIGNED_EXPIRY_SECONDS = 10 * 60

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
    ".php",
    ".py",
    ".html",
    ".htm",
}

DEFAULT_ALLOWED_EXTENSIONS = {
    ".pdf": "application/pdf",
    ".dwg": "application/acad",
    ".dxf": "image/vnd.dxf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}


def _drawing_root_prefix() -> str:
    return (
        getattr(settings, "DRAWING_FILES_S3_PREFIX", "Drawing") or "Drawing"
    ).strip().strip("/")


def _max_upload_size() -> int:
    return int(getattr(settings, "DRAWING_MAX_FILE_SIZE", 100 * 1024 * 1024))


def _allowed_extensions() -> dict[str, str]:
    configured = getattr(settings, "DRAWING_ALLOWED_EXTENSIONS", None)
    if isinstance(configured, dict) and configured:
        return {k.lower(): v for k, v in configured.items()}
    if isinstance(configured, (list, tuple, set)):
        out = {}
        for ext in configured:
            ext = str(ext).lower()
            if not ext.startswith("."):
                ext = f".{ext}"
            out[ext] = DEFAULT_ALLOWED_EXTENSIONS.get(ext, "application/octet-stream")
        return out or DEFAULT_ALLOWED_EXTENSIONS
    return DEFAULT_ALLOWED_EXTENSIONS


def check_s3_ready() -> tuple[bool, str | None]:
    if not is_boto3_available():
        return False, "boto3 is not installed. Run: pip install boto3"
    if not is_s3_configured():
        return False, "AWS S3 configuration missing"
    return True, None


def sanitize_filename(filename: str) -> str:
    safe = get_valid_filename(Path(filename or "drawing").name)
    return safe or "drawing"


def extension_for(filename: str) -> str:
    return Path(filename or "").suffix.lower()


def build_s3_key(
    *,
    project_id: int,
    register_id: int,
    revision: int,
    filename: str,
) -> str:
    ext = extension_for(filename) or ".bin"
    unique = uuid.uuid4().hex
    root = _drawing_root_prefix()
    return f"{root}/{int(project_id)}/{int(register_id)}/rev-{int(revision)}/{unique}{ext}"


def validate_upload_file(uploaded_file) -> tuple[str, str, str]:
    """
    Validate a single upload. Returns (original_filename, content_type, extension).
    """
    filename = sanitize_filename(getattr(uploaded_file, "name", "drawing"))
    ext = extension_for(filename)

    if ext in BLOCKED_EXTENSIONS:
        raise ValidationError(f"File type '{ext}' is not allowed.")
    allowed = _allowed_extensions()
    if ext not in allowed:
        allowed_list = ", ".join(sorted(allowed.keys()))
        raise ValidationError(
            f"Unsupported file type '{ext}'. Allowed: {allowed_list}."
        )

    size = int(getattr(uploaded_file, "size", 0) or 0)
    if size <= 0:
        raise ValidationError(f"File '{filename}' is empty or unreadable.")
    max_size = _max_upload_size()
    if size > max_size:
        mb = max_size // (1024 * 1024)
        raise ValidationError(
            f"File '{filename}' exceeds maximum size ({mb} MB)."
        )

    content_type = allowed.get(ext) or mimetypes.guess_type(filename)[0] or "application/octet-stream"

    uploaded_file.seek(0)
    header = uploaded_file.read(12) or b""
    uploaded_file.seek(0)
    if ext == ".pdf" and not header.startswith(b"%PDF"):
        raise ValidationError(f"Invalid PDF file: '{filename}'.")
    if ext in {".jpg", ".jpeg"} and not header.startswith(b"\xff\xd8\xff"):
        raise ValidationError(f"Invalid JPEG file: '{filename}'.")
    if ext == ".png" and not header.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValidationError(f"Invalid PNG file: '{filename}'.")

    return filename, content_type, ext


def _copy_to_spooled_file(source) -> tempfile.SpooledTemporaryFile:
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


def upload_drawing_file(
    *,
    uploaded_file,
    project_id: int,
    register_id: int,
    revision: int,
) -> dict:
    ready, err = check_s3_ready()
    if not ready:
        raise ValidationError(err or "S3 is not ready.")

    filename, content_type, ext = validate_upload_file(uploaded_file)
    s3_key = build_s3_key(
        project_id=project_id,
        register_id=register_id,
        revision=revision,
        filename=filename,
    )

    buffered = _copy_to_spooled_file(uploaded_file)
    size = _file_size(buffered)
    if size <= 0:
        buffered.close()
        raise ValidationError(f"File '{filename}' is empty or unreadable.")

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
                    "project-id": str(project_id),
                    "register-id": str(register_id),
                    "revision": str(revision),
                },
            },
        )
    finally:
        buffered.close()

    return {
        "s3_key": s3_key,
        "file_url": s3_public_url(s3_key),
        "original_filename": filename,
        "file_size": size,
        "content_type": content_type,
        "file_extension": ext.lstrip("."),
    }


def delete_drawing_file(s3_key: str) -> None:
    if not s3_key:
        return
    root = _drawing_root_prefix()
    key = s3_key.lstrip("/")
    if not key.startswith(f"{root}/"):
        logger.warning("Refusing to delete drawing file outside prefix: %s", s3_key)
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
        logger.exception("Failed to delete drawing file from S3: %s", s3_key)


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

    try:
        from services.presigned_url_cache import cached_presigned_url

        return cached_presigned_url(
            cache_namespace="drawing_files",
            s3_key=s3_key,
            expires_in=expires_in,
            generator=_sign,
        )
    except Exception:
        logger.debug("Presign cache unavailable; signing directly", exc_info=True)
        return _sign(s3_key, expires_in=expires_in)


def delete_drawing_files_batch(s3_keys: list[str]) -> None:
    for key in s3_keys:
        delete_drawing_file(key)
