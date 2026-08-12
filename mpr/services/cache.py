"""MPR preview cache — versioned RBAC keys, no FLUSHDB."""

from __future__ import annotations

from django.conf import settings
from django.core.cache import cache

from core.cache_keys import build_rbac_list_cache_key, invalidate_list_cache

CACHE_PREFIX = "mpr_preview_v1"
DEFAULT_TTL = 300  # 5 minutes


def mpr_cache_ttl() -> int:
    return int(getattr(settings, "MPR_PREVIEW_CACHE_TTL", DEFAULT_TTL))


def build_mpr_cache_key(request, project_id: int, month_key: str) -> str:
    return build_rbac_list_cache_key(
        CACHE_PREFIX,
        request,
        extra_parts=[f"project:{project_id}", f"month:{month_key}"],
        use_query_string=False,
    )


def get_cached_mpr(key: str):
    try:
        return cache.get(key)
    except Exception:
        return None


def set_cached_mpr(key: str, payload: dict) -> None:
    try:
        cache.set(key, payload, timeout=mpr_cache_ttl())
    except Exception:
        pass


def invalidate_mpr_cache() -> None:
    invalidate_list_cache(CACHE_PREFIX)
