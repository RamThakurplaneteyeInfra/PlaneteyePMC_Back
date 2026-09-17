"""
Cloudinary SDK configuration (lazy — never import from settings.py).

Call configure_cloudinary() before upload/delete operations.
"""

import importlib.util
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

_configured = False


def is_cloudinary_package_available() -> bool:
    """True if the PyPI cloudinary package is installed (not a local shadow module)."""
    spec = importlib.util.find_spec("cloudinary")
    if spec is None or spec.origin is None:
        return False
    # Reject a stray project file named cloudinary.py shadowing the real package
    origin = str(spec.origin)
    if origin.endswith("cloudinary.py"):
        logger.error(
            "A local file named cloudinary.py is shadowing the cloudinary package. "
            "Remove or rename it."
        )
        return False
    return True


def is_cloudinary_configured() -> bool:
    """True when all credential env vars are present in Django settings."""
    return bool(
        getattr(settings, "CLOUDINARY_CLOUD_NAME", "")
        and getattr(settings, "CLOUDINARY_API_KEY", "")
        and getattr(settings, "CLOUDINARY_API_SECRET", "")
    )


def configure_cloudinary() -> None:
    """
    Apply cloudinary.config() once using settings credentials.
    Imports the cloudinary package only when called.
    """
    global _configured

    if _configured:
        return

    if not is_cloudinary_configured():
        raise RuntimeError("Cloudinary configuration missing")

    if not is_cloudinary_package_available():
        raise RuntimeError(
            "Cloudinary Python package is not installed. Run: pip install cloudinary"
        )

    import cloudinary

    cloudinary.config(
        cloud_name=settings.CLOUDINARY_CLOUD_NAME,
        api_key=settings.CLOUDINARY_API_KEY,
        api_secret=settings.CLOUDINARY_API_SECRET,
        secure=True,
    )
    _configured = True
    logger.debug(
        "Cloudinary SDK configured for cloud=%s",
        settings.CLOUDINARY_CLOUD_NAME,
    )
