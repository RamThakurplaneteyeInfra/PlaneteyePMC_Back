"""
AWS S3 configuration helpers (lazy — credentials from Django settings).
"""

from __future__ import annotations

import logging

from django.conf import settings

logger = logging.getLogger(__name__)

_configured = False


def is_boto3_available() -> bool:
    try:
        import boto3  # noqa: F401
    except ImportError:
        return False
    return True


def is_s3_configured() -> bool:
    return bool(
        getattr(settings, "AWS_ACCESS_KEY_ID", "")
        and getattr(settings, "AWS_SECRET_ACCESS_KEY", "")
        and getattr(settings, "AWS_STORAGE_BUCKET_NAME", "")
    )


def get_s3_client():
    """Return a configured boto3 S3 client."""
    if not is_boto3_available():
        raise RuntimeError(
            "boto3 is not installed. Run: pip install boto3"
        )
    if not is_s3_configured():
        raise RuntimeError("AWS S3 configuration missing")

    import boto3

    return boto3.client(
        "s3",
        region_name=getattr(settings, "AWS_S3_REGION_NAME", "ap-south-1"),
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
    )


def s3_public_url(object_key: str) -> str:
    """Build the public HTTPS URL for an object key."""
    bucket = settings.AWS_STORAGE_BUCKET_NAME
    region = getattr(settings, "AWS_S3_REGION_NAME", "ap-south-1")
    custom_domain = getattr(settings, "AWS_S3_CUSTOM_DOMAIN", "").strip()
    key = object_key.lstrip("/")

    if custom_domain:
        return f"https://{custom_domain.rstrip('/')}/{key}"

    return f"https://{bucket}.s3.{region}.amazonaws.com/{key}"
