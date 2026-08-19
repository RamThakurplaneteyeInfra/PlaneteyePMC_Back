"""
RBAC-aware cache key helpers for list endpoints.

Ensures cached list payloads are scoped to the set of projects a user can
see, so one user's response cannot be served to another with different access.

Dataset reuse: users who see the exact same project set (e.g. all admins, or
two engineers assigned to the same projects) share the same scope token.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Iterable
from typing import Any

from django.core.cache import cache

logger = logging.getLogger(__name__)


def _version_key(prefix: str) -> str:
    # Separate namespace so delete_pattern(f"{prefix}:*") never clears the counter.
    return f"_rbac_cache_ver:{prefix}"


def get_list_cache_version(prefix: str) -> int:
    try:
        return int(cache.get(_version_key(prefix)) or 0)
    except (TypeError, ValueError):
        return 0


def bump_list_cache_version(prefix: str) -> int:
    key = _version_key(prefix)
    try:
        return int(cache.incr(key))
    except ValueError:
        cache.set(key, 1, timeout=None)
        return 1


def bump_many_list_cache_versions(prefixes: Iterable[str]) -> list[str]:
    """
    Bump many list-cache versions in one Redis round trip when possible.

    SCAN/delete_pattern is intentionally not used: versioned keys
    (``prefix:vN:...``) become unreachable after the bump.
    """
    unique = [str(p) for p in dict.fromkeys(prefixes) if p]
    if not unique:
        return []

    client_getter = getattr(getattr(cache, "client", None), "get_client", None)
    if callable(client_getter):
        try:
            redis_client = client_getter(write=True)
            pipe = redis_client.pipeline(transaction=False)
            make_key = getattr(cache, "make_key", None)
            started = time.perf_counter()
            for prefix in unique:
                raw = _version_key(prefix)
                redis_key = make_key(raw) if callable(make_key) else raw
                pipe.incr(redis_key)
            pipe.execute()
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.info(
                "cache_invalidate_pipeline count=%s duration_ms=%.1f",
                len(unique),
                elapsed_ms,
            )
            return unique
        except Exception as exc:
            logger.debug("cache pipeline incr fallback: %s", exc)

    for prefix in unique:
        bump_list_cache_version(prefix)
    return unique


def rbac_dataset_scope(user) -> str:
    """
    Stable token for the project dataset visible to *user*.

    - admin / superuser → ``admin`` (full dataset; shared across admins)
    - assigned projects → ``p{sha256(sorted ids)[:16]}``
    - none / anonymous → ``none`` / ``anon``
    """
    if not user or not getattr(user, "is_authenticated", False):
        return "anon"

    # Lazy import avoids circular imports at Django startup.
    from accounts.rbac import get_user_assigned_project_ids, is_admin_user

    if getattr(user, "is_superuser", False) or is_admin_user(user):
        return "admin"

    ids = sorted(get_user_assigned_project_ids(user))
    if not ids:
        return "none"
    digest = hashlib.sha256(",".join(str(i) for i in ids).encode("utf-8")).hexdigest()
    return f"p{digest[:16]}"


def _hash_parts(parts: Iterable[str]) -> str:
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def build_rbac_list_cache_key(
    prefix: str,
    request: Any,
    *,
    extra_parts: Iterable[str] | None = None,
    use_query_string: bool = True,
) -> str:
    """
    Build a deterministic list cache key.

    Format: ``{prefix}:v{version}:s{scope}:{filter_token}``

    - *prefix*: module namespace (e.g. ``invoicing_list``)
    - *version*: bumped on write invalidation
    - *scope*: RBAC dataset token (shared when visibility matches)
    - *filter_token*: query string and/or explicit filter parts
    """
    user = getattr(request, "user", None)
    scope = rbac_dataset_scope(user)
    version = get_list_cache_version(prefix)

    filter_bits: list[str] = []
    if extra_parts:
        filter_bits.extend(str(p) for p in extra_parts if p is not None and str(p) != "")

    if use_query_string and request is not None:
        qs = ""
        meta = getattr(request, "META", None) or {}
        qs = meta.get("QUERY_STRING") or ""
        if not qs:
            query_params = getattr(request, "query_params", None)
            if query_params is not None:
                try:
                    # Preserve deterministic ordering of multi-value params.
                    items = []
                    for key in sorted(query_params.keys()):
                        values = query_params.getlist(key)
                        for value in values:
                            items.append(f"{key}={value}")
                    qs = "&".join(items)
                except Exception:
                    qs = str(query_params)
        if qs:
            filter_bits.append(f"qs:{qs}")

    filter_token = _hash_parts(filter_bits) if filter_bits else "default"
    return f"{prefix}:v{version}:s{scope}:{filter_token}"


def invalidate_list_cache(prefix: str, *legacy_keys: str) -> None:
    """
    Invalidate all list cache entries for *prefix* by bumping the version.

    Versioned keys (``prefix:vN:...``) are unreachable after the bump, so this
    does not SCAN/delete_pattern. Remote Redis SCAN was measured at ~1–2s per
    prefix and dominated live DPR writes (42 scans ≈ 48s).

    Exact *legacy_keys* are still deleted. Bare prefix delete is skipped unless
    CACHE_INVALIDATE_SCAN is enabled (legacy SCAN path).
    """
    from django.conf import settings

    try:
        bump_list_cache_version(prefix)
        logger.info("cache_invalidate prefix=%s", prefix)
    except Exception as exc:
        logger.warning("Failed to bump cache version for %s: %s", prefix, exc)

    if getattr(settings, "CACHE_INVALIDATE_SCAN", False):
        try:
            if hasattr(cache, "delete_pattern"):
                cache.delete_pattern(f"{prefix}:*")
        except Exception as exc:
            logger.debug("delete_pattern unavailable for %s: %s", prefix, exc)
        for key in (prefix, *legacy_keys):
            if not key:
                continue
            try:
                cache.delete(key)
            except Exception:
                pass
        return

    for key in legacy_keys:
        if not key:
            continue
        try:
            cache.delete(key)
        except Exception:
            pass
