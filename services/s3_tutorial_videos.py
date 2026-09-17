"""
S3 helpers for tutorial videos.

Keys under settings.TUTORIAL_VIDEOS_S3_PREFIX (default ``tutorial``):
  tutorial/temporary/{uuid}{ext}
  tutorial/optimized/{uuid}.mp4

Public URL example:
  https://pmcproject.s3.ap-south-1.amazonaws.com/tutorial/...
"""

from __future__ import annotations

import logging
import mimetypes
import tempfile
import uuid
from pathlib import Path

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

logger = logging.getLogger("pmc.tutorial_videos.s3")

PRESIGNED_EXPIRY_SECONDS = 10 * 60

ALLOWED_EXTENSIONS = {
    ".mp4": "video/mp4",
    ".m4v": "video/x-m4v",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
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

# Magic signatures (offset, bytes) for practical content sniffing.
_MAGIC_CHECKS = (
    (4, b"ftyp"),  # MP4 / MOV / M4V
    (0, b"\x1a\x45\xdf\xa3"),  # WebM / Matroska
    (0, b"RIFF"),  # AVI (also check AVI later)
)


def tutorial_root() -> str:
    return (
        str(getattr(settings, "TUTORIAL_VIDEOS_S3_PREFIX", "tutorial")).strip("/")
        or "tutorial"
    )


def max_upload_bytes() -> int:
    try:
        mb = int(getattr(settings, "TUTORIAL_VIDEO_MAX_UPLOAD_MB", 500))
    except (TypeError, ValueError):
        mb = 500
    return max(1, mb) * 1024 * 1024


def check_s3_ready() -> tuple[bool, str | None]:
    if not is_boto3_available():
        return False, "boto3 is not installed. Run: pip install boto3"
    if not is_s3_configured():
        return False, "AWS S3 configuration missing"
    return True, None


def sanitize_filename(filename: str) -> str:
    safe = get_valid_filename(Path(filename or "video").name)
    return safe or "video"


def extension_for(filename: str) -> str:
    return Path(filename or "").suffix.lower()


def content_type_for(filename: str) -> str:
    ext = extension_for(filename)
    if ext in ALLOWED_EXTENSIONS:
        return ALLOWED_EXTENSIONS[ext]
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def sniff_looks_like_video(header: bytes, *, filename: str = "") -> bool:
    """Best-effort content check; does not replace FFmpeg validation."""
    if not header:
        return False
    for offset, sig in _MAGIC_CHECKS:
        if len(header) >= offset + len(sig) and header[offset : offset + len(sig)] == sig:
            if sig == b"RIFF":
                return len(header) >= 12 and header[8:11] == b"AVI"
            return True
    # Fallback: trusted extension + non-empty binary (FFmpeg will reject junk).
    ext = extension_for(filename)
    return ext in ALLOWED_EXTENSIONS and len(header) > 32


def validate_upload_file(uploaded_file) -> tuple[str, str]:
    """Returns (safe_filename, content_type)."""
    filename = sanitize_filename(getattr(uploaded_file, "name", "video"))
    ext = extension_for(filename)
    if ext in BLOCKED_EXTENSIONS:
        raise ValidationError("Executable files are not allowed.")
    if not ext or ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(
            "Unsupported video type. Allowed: MP4, M4V, MOV, WebM, AVI, MKV."
        )

    size = getattr(uploaded_file, "size", None)
    limit = max_upload_bytes()
    if size is not None and size > limit:
        raise ValidationError(
            f"File exceeds maximum size of {limit // (1024 * 1024)} MB."
        )
    if size is not None and size <= 0:
        raise ValidationError("Uploaded video is empty or unreadable.")

    # Sniff first chunk without trusting client Content-Type.
    pos = uploaded_file.tell() if hasattr(uploaded_file, "tell") else 0
    try:
        uploaded_file.seek(0)
        header = uploaded_file.read(64) or b""
    finally:
        try:
            uploaded_file.seek(pos)
        except Exception:
            uploaded_file.seek(0)

    if not sniff_looks_like_video(header, filename=filename):
        raise ValidationError("File content does not look like a valid video.")

    return filename, content_type_for(filename)


def build_temp_key(*, filename: str) -> str:
    ext = extension_for(filename) or ".mp4"
    return f"{tutorial_root()}/temporary/{uuid.uuid4().hex}{ext}"


def build_optimized_key() -> str:
    return f"{tutorial_root()}/optimized/{uuid.uuid4().hex}.mp4"


def object_url(s3_key: str) -> str:
    return s3_public_url(s3_key)


def upload_bytes_or_fileobj(
    *,
    fileobj,
    s3_key: str,
    content_type: str,
    metadata: dict | None = None,
) -> int:
    """Upload file-like object; returns byte size written."""
    ready, err = check_s3_ready()
    if not ready:
        raise ValidationError(err or "S3 is not ready.")

    fileobj.seek(0)
    size = 0
    buffered = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)
    try:
        limit = max_upload_bytes()
        while True:
            chunk = fileobj.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise ValidationError(
                    f"File exceeds maximum size of {limit // (1024 * 1024)} MB."
                )
            buffered.write(chunk)
        if size <= 0:
            raise ValidationError("Uploaded video is empty or unreadable.")

        buffered.seek(0)
        extra = {
            "ContentType": content_type,
            "CacheControl": DEFAULT_OBJECT_CACHE_CONTROL,
        }
        if metadata:
            extra["Metadata"] = {str(k)[:50]: str(v)[:200] for k, v in metadata.items()}

        get_s3_client().upload_fileobj(
            buffered,
            settings.AWS_STORAGE_BUCKET_NAME,
            s3_key,
            ExtraArgs=extra,
        )
        logger.info("Tutorial S3 upload ok key=%s size=%s", s3_key, size)
        return size
    finally:
        try:
            buffered.close()
        except Exception:
            pass


def upload_local_file(
    *,
    local_path: str,
    s3_key: str,
    content_type: str = "video/mp4",
    metadata: dict | None = None,
) -> int:
    ready, err = check_s3_ready()
    if not ready:
        raise ValidationError(err or "S3 is not ready.")

    path = Path(local_path)
    if not path.is_file():
        raise ValidationError("Local video file missing for S3 upload.")
    size = path.stat().st_size
    extra = {
        "ContentType": content_type,
        "CacheControl": DEFAULT_OBJECT_CACHE_CONTROL,
    }
    if metadata:
        extra["Metadata"] = {str(k)[:50]: str(v)[:200] for k, v in metadata.items()}

    get_s3_client().upload_file(
        str(path),
        settings.AWS_STORAGE_BUCKET_NAME,
        s3_key,
        ExtraArgs=extra,
    )
    logger.info("Tutorial S3 upload_file ok key=%s size=%s", s3_key, size)
    return size


def download_to_path(s3_key: str, dest_path: str) -> None:
    ready, err = check_s3_ready()
    if not ready:
        raise ValidationError(err or "S3 is not ready.")
    get_s3_client().download_file(
        settings.AWS_STORAGE_BUCKET_NAME,
        s3_key,
        dest_path,
    )


def delete_object(s3_key: str) -> None:
    if not s3_key:
        return
    root = tutorial_root() + "/"
    if not str(s3_key).startswith(root):
        logger.warning("Refusing to delete non-tutorial key: %s", s3_key)
        return
    ready, message = check_s3_ready()
    if not ready:
        logger.warning("S3 not ready; skip delete for %s (%s)", s3_key, message)
        return
    try:
        get_s3_client().delete_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            Key=s3_key,
        )
        logger.info("Tutorial S3 delete ok key=%s", s3_key)
    except Exception:
        logger.exception("Failed to delete tutorial object: %s", s3_key)


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
                "ResponseContentType": "video/mp4",
            },
            ExpiresIn=expires_in,
        )

    from services.presigned_url_cache import cached_presigned_url

    return cached_presigned_url(
        cache_namespace="tutorial_videos",
        s3_key=s3_key,
        expires_in=expires_in,
        generator=_sign,
    )
