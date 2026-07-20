"""
Cached presigned S3 URL helpers.

Preserves identical URL responses while avoiding repeated SigV4 work for the
same object key within the URL lifetime. Uses Django's configured cache
backend (LocMem in tests/dev is fine — no Redis required).
"""

from __future__ import annotations

import hashlib
import logging
import sys

from django.core.cache import cache

logger = logging.getLogger(__name__)


def cached_presigned_url(
    *,
    cache_namespace: str,
    s3_key: str,
    expires_in: int,
    generator,
) -> str:
    """
    Return a presigned URL, reusing a cached value when still fresh.

    Cache TTL is slightly shorter than *expires_in* so clients never receive
    a URL that is about to expire.

    Caching is skipped under the Django test runner so mocked S3 clients and
    per-test expectations remain deterministic.
    """
    if not s3_key:
        return generator(s3_key, expires_in=expires_in)

    if "test" in sys.argv:
        return generator(s3_key, expires_in=expires_in)

    key_hash = hashlib.sha256(s3_key.encode("utf-8")).hexdigest()[:32]
    cache_key = f"presign:{cache_namespace}:{expires_in}:{key_hash}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    url = generator(s3_key, expires_in=expires_in)
    ttl = max(int(expires_in) - 60, 30)
    try:
        cache.set(cache_key, url, ttl)
    except Exception as exc:
        logger.debug("Presigned URL cache set failed: %s", exc)
    return url
