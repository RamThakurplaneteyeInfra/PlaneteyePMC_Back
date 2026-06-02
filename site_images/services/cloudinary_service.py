"""
Cloudinary upload/delete helpers.

Package must be installed (see requirements.txt).
Configuration is applied in backend/settings.py at startup.
"""

import logging

from django.conf import settings

logger = logging.getLogger(__name__)

try:
    import cloudinary
    import cloudinary.uploader
except ImportError:  # pragma: no cover — handled via CLOUDINARY_AVAILABLE
    cloudinary = None  # type: ignore[assignment]
    cloudinary_uploader = None  # type: ignore[assignment,misc]
else:
    cloudinary_uploader = cloudinary.uploader

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_IMAGES_PER_REQUEST = 20


def is_cloudinary_available() -> bool:
    return bool(getattr(settings, "CLOUDINARY_AVAILABLE", False))


def is_cloudinary_configured() -> bool:
    return bool(getattr(settings, "CLOUDINARY_CONFIGURED", False))


def check_cloudinary_ready() -> tuple[bool, str | None]:
    if not is_cloudinary_available():
        return (
            False,
            "Cloudinary Python package is not installed. "
            "Run: pip install cloudinary",
        )
    if not is_cloudinary_configured():
        return False, "Cloudinary configuration missing"
    return True, None


def build_upload_folder(project_name: str, year: int, month: int) -> str:
    return f"pmc/{project_name.strip()}/{year}/{month:02d}"


def validate_image_file(uploaded_file) -> None:
    name = getattr(uploaded_file, "name", "") or ""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"Unsupported format '{ext or 'unknown'}'. "
            f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}."
        )

    size = getattr(uploaded_file, "size", None)
    if size is not None and size > MAX_FILE_BYTES:
        raise ValueError(f"File '{name}' exceeds maximum size of 10 MB.")


def upload_image(uploaded_file, *, folder: str) -> dict:
    ready, message = check_cloudinary_ready()
    if not ready:
        raise RuntimeError(message)

    validate_image_file(uploaded_file)
    file_name = getattr(uploaded_file, "name", "unknown")

    logger.info("Cloudinary upload start: file=%s folder=%s", file_name, folder)

    if cloudinary_uploader is None:
        raise RuntimeError(
            "Cloudinary Python package is not installed. Run: pip install cloudinary"
        )

    try:
        result = cloudinary_uploader.upload(
            uploaded_file,
            folder=folder,
            resource_type="image",
            use_filename=True,
            unique_filename=True,
            overwrite=False,
        )
    except Exception as exc:
        logger.exception(
            "Cloudinary upload failure: file=%s folder=%s error=%s",
            file_name,
            folder,
            exc,
        )
        raise

    public_id = result.get("public_id", "")
    secure_url = result.get("secure_url") or result.get("url", "")

    logger.info(
        "Cloudinary upload success: file=%s public_id=%s",
        file_name,
        public_id,
    )

    return {"secure_url": secure_url, "public_id": public_id}


def delete_image(public_id: str) -> None:
    if not public_id:
        return

    ready, message = check_cloudinary_ready()
    if not ready:
        logger.warning("Cloudinary delete skipped: %s", message)
        return

    if cloudinary_uploader is None:
        raise RuntimeError(
            "Cloudinary Python package is not installed. Run: pip install cloudinary"
        )

    logger.info("Cloudinary delete start: public_id=%s", public_id)
    try:
        cloudinary_uploader.destroy(public_id, resource_type="image")
        logger.info("Cloudinary delete success: public_id=%s", public_id)
    except Exception as exc:
        logger.exception(
            "Cloudinary delete failure: public_id=%s error=%s",
            public_id,
            exc,
        )
        raise
