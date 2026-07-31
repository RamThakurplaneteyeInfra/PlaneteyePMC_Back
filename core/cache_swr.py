"""
Stale-while-revalidate + stampede protection for expensive cache rebuilds.

Extends ``core.cache_ops`` without breaking existing ``cache_get`` / ``cache_set``.

Envelope stored in cache::

    {
      "_pmc_swr": True,
      "payload": <any>,
      "soft_expires_at": <epoch seconds>,
      "hard_expires_at": <epoch seconds>,
    }

- Before soft expiry → fresh hit
- Between soft and hard → stale hit + single rebuild under lock
- After hard expiry → miss + single rebuild under lock
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any, TypeVar

from django.core.cache import cache

from core.cache_metrics import (
    Timer,
    record_hit,
    record_lock_wait_timeout,
    record_miss,
    record_rebuild,
)
from core.cache_ops import TTL_DEFAULT, cache_get, cache_set

logger = logging.getLogger("pmc.cache.swr")

T = TypeVar("T")

_SWR_MARKER = "_pmc_swr"
_LOCK_PREFIX = "_pmc:lock:"


def _now() -> float:
    return time.time()


def _wrap_payload(payload: Any, soft_ttl: int, hard_ttl: int) -> dict[str, Any]:
    now = _now()
    return {
        _SWR_MARKER: True,
        "payload": payload,
        "soft_expires_at": now + soft_ttl,
        "hard_expires_at": now + hard_ttl,
        "cached_at": now,
    }


def _unwrap(value: Any) -> tuple[Any, float, float] | None:
    if isinstance(value, dict) and value.get(_SWR_MARKER) is True:
        return (
            value.get("payload"),
            float(value.get("soft_expires_at") or 0),
            float(value.get("hard_expires_at") or 0),
        )
    # Legacy plain cache values — treat as soft-fresh until key TTL expires.
    if value is not None:
        far = _now() + 86400 * 365
        return value, far, far
    return None


def acquire_lock(key: str, *, timeout: int = 30) -> bool:
    """Distributed lock via cache.add (atomic on Redis)."""
    lock_key = f"{_LOCK_PREFIX}{key}"
    try:
        return bool(cache.add(lock_key, "1", timeout))
    except Exception as exc:
        logger.debug("lock acquire failed key=%s err=%s", key, exc)
        return True  # fail open — allow rebuild rather than stall forever


def release_lock(key: str) -> None:
    lock_key = f"{_LOCK_PREFIX}{key}"
    try:
        cache.delete(lock_key)
    except Exception:
        pass


def wait_for_cache(
    key: str,
    *,
    prefix: str = "",
    attempts: int = 5,
    sleep_s: float = 0.05,
) -> Any | None:
    for _ in range(max(1, attempts)):
        value = cache_get(key, prefix=prefix)
        unwrapped = _unwrap(value)
        if unwrapped is not None:
            return unwrapped[0]
        time.sleep(sleep_s)
    return None


def swr_set(
    key: str,
    payload: Any,
    *,
    soft_ttl: int | None = None,
    hard_ttl: int | None = None,
    prefix: str = "",
) -> bool:
    soft = int(soft_ttl if soft_ttl is not None else TTL_DEFAULT)
    hard = int(hard_ttl if hard_ttl is not None else soft * 2)
    if hard < soft:
        hard = soft
    envelope = _wrap_payload(payload, soft, hard)
    return cache_set(key, envelope, hard, prefix=prefix)


def get_or_rebuild(
    key: str,
    builder: Callable[[], T],
    *,
    soft_ttl: int | None = None,
    hard_ttl: int | None = None,
    prefix: str = "",
    lock_timeout: int = 30,
    wait_attempts: int = 5,
    async_revalidate: Callable[[], None] | None = None,
) -> T:
    """
    Fetch cached value with stampede protection and stale-while-revalidate.

    ``async_revalidate`` — optional callback (e.g. Celery task) invoked when
    serving stale data; if None, rebuilds synchronously under the lock.
    """
    timer = Timer()
    raw = cache_get(key, prefix=prefix)
    unwrapped = _unwrap(raw)
    now = _now()

    if unwrapped is not None:
        payload, soft_at, hard_at = unwrapped
        if now <= soft_at:
            record_hit(stale=False, lookup_ms=timer.ms())
            return payload  # type: ignore[return-value]

        if now <= hard_at:
            # Stale but usable — return immediately and refresh once.
            record_hit(stale=True, lookup_ms=timer.ms())
            if acquire_lock(key, timeout=lock_timeout):
                try:
                    if async_revalidate is not None:
                        try:
                            async_revalidate()
                        except Exception as exc:
                            logger.warning("async revalidate failed: %s", exc)
                            # Fall through to sync rebuild
                            _rebuild_and_store(
                                key,
                                builder,
                                soft_ttl=soft_ttl,
                                hard_ttl=hard_ttl,
                                prefix=prefix,
                            )
                    else:
                        _rebuild_and_store(
                            key,
                            builder,
                            soft_ttl=soft_ttl,
                            hard_ttl=hard_ttl,
                            prefix=prefix,
                        )
                finally:
                    release_lock(key)
            return payload  # type: ignore[return-value]

    # Hard miss
    record_miss(lookup_ms=timer.ms())
    if acquire_lock(key, timeout=lock_timeout):
        try:
            # Double-check after lock — another worker may have filled it.
            raw2 = cache_get(key, prefix=prefix)
            unwrapped2 = _unwrap(raw2)
            if unwrapped2 is not None and _now() <= unwrapped2[1]:
                return unwrapped2[0]  # type: ignore[return-value]
            return _rebuild_and_store(
                key,
                builder,
                soft_ttl=soft_ttl,
                hard_ttl=hard_ttl,
                prefix=prefix,
            )
        finally:
            release_lock(key)

    # Lock held by another worker — wait briefly for fill.
    waited = wait_for_cache(
        key, prefix=prefix, attempts=wait_attempts, sleep_s=0.05
    )
    if waited is not None:
        return waited  # type: ignore[return-value]

    record_lock_wait_timeout()
    # Last resort: build without lock (prefer availability).
    return _rebuild_and_store(
        key,
        builder,
        soft_ttl=soft_ttl,
        hard_ttl=hard_ttl,
        prefix=prefix,
    )


def _rebuild_and_store(
    key: str,
    builder: Callable[[], T],
    *,
    soft_ttl: int | None,
    hard_ttl: int | None,
    prefix: str,
) -> T:
    timer = Timer()
    try:
        payload = builder()
        swr_set(
            key,
            payload,
            soft_ttl=soft_ttl,
            hard_ttl=hard_ttl,
            prefix=prefix,
        )
        record_rebuild(rebuild_ms=timer.ms(), error=False)
        return payload
    except Exception:
        record_rebuild(rebuild_ms=timer.ms(), error=True)
        raise
