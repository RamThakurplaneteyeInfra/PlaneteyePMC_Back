"""
Safe cache helpers with hit/miss logging and Redis-failure resilience.

Uses Django's cache framework (Redis via django-redis when configured,
LocMem otherwise). Never raises to callers — Redis outages fall through
to compute-from-DB paths.
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger("pmc.cache")

# Named TTLs (seconds) — override via settings if needed.
TTL_OVERVIEW = int(getattr(settings, "CACHE_TTL_OVERVIEW", 300))  # 5 min
TTL_DASHBOARD = int(getattr(settings, "CACHE_TTL_DASHBOARD", 300))  # 5 min
TTL_DROPDOWN = int(getattr(settings, "CACHE_TTL_DROPDOWN", 1800))  # 30 min
TTL_REPORT = int(getattr(settings, "CACHE_TTL_REPORT", 900))  # 15 min
TTL_REFERENCE = int(getattr(settings, "CACHE_TTL_REFERENCE", 3600))  # 1 hour
TTL_DEFAULT = int(getattr(settings, "CACHE_TTL_DEFAULT", 300))


def cache_get(key: str, *, prefix: str = "") -> Any | None:
    """Return cached value or None. Logs hit/miss; never raises."""
    try:
        value = cache.get(key)
    except Exception as exc:
        logger.warning("cache_get error key=%s err=%s", key, exc)
        return None
    if value is None:
        logger.debug("cache_miss prefix=%s key=%s", prefix or key.split(":")[0], key)
        return None
    logger.debug("cache_hit prefix=%s key=%s", prefix or key.split(":")[0], key)
    return value


def cache_set(key: str, value: Any, timeout: int | None = None, *, prefix: str = "") -> bool:
    """Store value. Returns False on failure (caller should ignore)."""
    ttl = TTL_DEFAULT if timeout is None else timeout
    try:
        cache.set(key, value, ttl)
        logger.debug(
            "cache_set prefix=%s key=%s ttl=%s",
            prefix or key.split(":")[0],
            key,
            ttl,
        )
        return True
    except Exception as exc:
        logger.warning("cache_set error key=%s err=%s", key, exc)
        return False


def cache_delete(key: str) -> None:
    try:
        cache.delete(key)
    except Exception as exc:
        logger.debug("cache_delete error key=%s err=%s", key, exc)


# Re-exports for enterprise helpers (backward-compatible import path).
def get_or_rebuild(*args, **kwargs):
    from core.cache_swr import get_or_rebuild as _impl

    return _impl(*args, **kwargs)


def invalidate_tags(*tags: str):
    from core.cache_tags import invalidate_tags as _impl

    return _impl(*tags)


def batch_cache_invalidation():
    from core.cache_tags import batch_cache_invalidation as _impl

    return _impl()
