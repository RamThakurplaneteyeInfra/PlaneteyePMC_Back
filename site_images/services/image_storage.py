"""
Unified site image storage — AWS S3 primary, Cloudinary fallback.
"""

from __future__ import annotations

import logging

from django.conf import settings

from . import cloudinary_service, s3_service

logger = logging.getLogger(__name__)

STORAGE_S3 = "s3"
STORAGE_CLOUDINARY = "cloudinary"


def build_upload_folder(project_name: str, year: int, month: int) -> str:
    """Relative folder segment shared by S3 key layout and Cloudinary folder."""
    return f"{project_name.strip()}/{year}/{month:02d}"


def _s3_only_mode() -> bool:
    return bool(getattr(settings, "SITE_IMAGE_S3_ONLY", False))


def _primary_backend() -> str:
    if _s3_only_mode():
        return STORAGE_S3
    value = getattr(settings, "SITE_IMAGE_STORAGE_PRIMARY", "s3").strip().lower()
    return value if value in (STORAGE_S3, STORAGE_CLOUDINARY) else STORAGE_S3


def check_storage_ready() -> tuple[bool, str | None]:
    """True when S3 (or Cloudinary fallback) is configured."""
    s3_ready, s3_msg = s3_service.check_s3_ready()
    if _s3_only_mode():
        if s3_ready:
            return True, None
        return False, s3_msg

    cloud_ready, cloud_msg = cloudinary_service.check_cloudinary_ready()
    if s3_ready or cloud_ready:
        return True, None
    return False, f"S3: {s3_msg}; Cloudinary: {cloud_msg}"


def upload_image(uploaded_file, *, folder: str) -> dict:
    """
    Upload using the configured primary backend, falling back to the other.

    Returns dict with secure_url, public_id (storage key), storage_backend.
    """
    primary = _primary_backend()
    if _s3_only_mode():
        backends = [STORAGE_S3]
    else:
        backends = (
            [STORAGE_S3, STORAGE_CLOUDINARY]
            if primary == STORAGE_S3
            else [STORAGE_CLOUDINARY, STORAGE_S3]
        )

    last_error: Exception | None = None

    for backend in backends:
        if backend == STORAGE_S3:
            ready, message = s3_service.check_s3_ready()
            if not ready:
                last_error = RuntimeError(message)
                continue
            try:
                if backend != primary:
                    logger.warning(
                        "Falling back to S3 for site image upload (primary=%s failed)",
                        primary,
                    )
                result = s3_service.upload_image(uploaded_file, folder=folder)
                result.setdefault("storage_backend", STORAGE_S3)
                return result
            except Exception as exc:
                last_error = exc
                logger.warning("S3 upload failed: %s", exc)
                uploaded_file.seek(0)
                continue

        ready, message = cloudinary_service.check_cloudinary_ready()
        if not ready:
            last_error = RuntimeError(message)
            continue
        try:
            if backend != primary:
                logger.warning(
                    "Falling back to Cloudinary for site image upload (primary=%s failed)",
                    primary,
                )
            cloud_folder = f"pmc/{folder}"
            result = cloudinary_service.upload_image(uploaded_file, folder=cloud_folder)
            result["storage_backend"] = STORAGE_CLOUDINARY
            return result
        except Exception as exc:
            last_error = exc
            logger.warning("Cloudinary upload failed: %s", exc)
            uploaded_file.seek(0)

    raise RuntimeError(str(last_error) if last_error else "No storage backend available")


def delete_image(storage_key: str, storage_backend: str) -> None:
    """Delete from the backend that originally stored the file."""
    if storage_backend == STORAGE_S3:
        s3_service.delete_image(storage_key)
        return
    if _s3_only_mode():
        logger.warning(
            "Cloudinary delete skipped (SITE_IMAGE_S3_ONLY): key=%s",
            storage_key,
        )
        return
    cloudinary_service.delete_image(storage_key)
