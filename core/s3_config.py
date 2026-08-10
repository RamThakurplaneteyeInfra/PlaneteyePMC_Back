"""
AWS S3 configuration helpers (lazy — credentials from Django settings).

Uses a process-wide shared boto3 client so View/download paths do not pay
client construction cost on every request.
"""

from __future__ import annotations

import logging
import threading
from urllib.parse import quote

from django.conf import settings

logger = logging.getLogger(__name__)

_client = None
_client_lock = threading.Lock()
_client_fingerprint: tuple | None = None


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


def _s3_region() -> str:
    return getattr(settings, "AWS_S3_REGION_NAME", "ap-south-1") or "ap-south-1"


def _client_config_fingerprint() -> tuple:
    return (
        settings.AWS_ACCESS_KEY_ID,
        settings.AWS_SECRET_ACCESS_KEY,
        getattr(settings, "AWS_STORAGE_BUCKET_NAME", ""),
        _s3_region(),
    )


def get_s3_client():
    """
    Return a shared boto3 S3 client.

    Uses a regional endpoint so presigned URLs match
    ``https://{bucket}.s3.{region}.amazonaws.com/...`` (avoids signature /
    403 failures against the legacy global ``s3.amazonaws.com`` host).
    """
    global _client, _client_fingerprint

    if not is_boto3_available():
        raise RuntimeError("boto3 is not installed. Run: pip install boto3")
    if not is_s3_configured():
        raise RuntimeError("AWS S3 configuration missing")

    fingerprint = _client_config_fingerprint()
    if _client is not None and _client_fingerprint == fingerprint:
        return _client

    with _client_lock:
        if _client is not None and _client_fingerprint == fingerprint:
            return _client

        import boto3
        from botocore.config import Config

        region = _s3_region()
        _client = boto3.client(
            "s3",
            region_name=region,
            endpoint_url=f"https://s3.{region}.amazonaws.com",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "virtual"},
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )
        _client_fingerprint = fingerprint
        logger.debug("S3 client initialized region=%s", region)
        return _client


def s3_public_url(object_key: str) -> str:
    """Build the public HTTPS URL for an object key (path segments encoded)."""
    bucket = settings.AWS_STORAGE_BUCKET_NAME
    region = _s3_region()
    custom_domain = getattr(settings, "AWS_S3_CUSTOM_DOMAIN", "").strip()
    key = object_key.lstrip("/")
    # Encode each path segment; keep "/" separators (S3 object key semantics).
    encoded = "/".join(quote(part, safe="") for part in key.split("/"))

    if custom_domain:
        return f"https://{custom_domain.rstrip('/')}/{encoded}"

    return f"https://{bucket}.s3.{region}.amazonaws.com/{encoded}"


# Default Cache-Control for newly uploaded objects (browser / CDN reuse on View).
DEFAULT_OBJECT_CACHE_CONTROL = "public, max-age=86400, immutable"
