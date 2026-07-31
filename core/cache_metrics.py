"""
In-process cache metrics (hit/miss/rebuild/invalidate).

Counters live in Django cache so they survive across workers when Redis is up,
and degrade gracefully on LocMem.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from django.core.cache import cache

logger = logging.getLogger("pmc.cache.metrics")

_METRICS_KEY = "_pmc:cache_metrics:v1"
_LOCK_KEY = "_pmc:cache_metrics:lock"


def _default_metrics() -> dict[str, Any]:
    return {
        "hits": 0,
        "misses": 0,
        "stale_hits": 0,
        "rebuilds": 0,
        "rebuild_errors": 0,
        "invalidations": 0,
        "lock_wait_timeouts": 0,
        "slow_rebuilds": 0,
        "total_lookup_ms": 0.0,
        "total_rebuild_ms": 0.0,
        "lookup_samples": 0,
        "rebuild_samples": 0,
        "largest_rebuild_ms": 0.0,
    }


def _load() -> dict[str, Any]:
    try:
        data = cache.get(_METRICS_KEY)
        if isinstance(data, dict):
            base = _default_metrics()
            base.update(data)
            return base
    except Exception:
        pass
    return _default_metrics()


def _save(data: dict[str, Any]) -> None:
    try:
        cache.set(_METRICS_KEY, data, timeout=None)
    except Exception as exc:
        logger.debug("metrics save failed: %s", exc)


def record_hit(*, stale: bool = False, lookup_ms: float = 0.0) -> None:
    data = _load()
    if stale:
        data["stale_hits"] += 1
    else:
        data["hits"] += 1
    data["total_lookup_ms"] += float(lookup_ms)
    data["lookup_samples"] += 1
    _save(data)


def record_miss(*, lookup_ms: float = 0.0) -> None:
    data = _load()
    data["misses"] += 1
    data["total_lookup_ms"] += float(lookup_ms)
    data["lookup_samples"] += 1
    _save(data)


def record_rebuild(*, rebuild_ms: float = 0.0, error: bool = False) -> None:
    from django.conf import settings

    slow_ms = float(getattr(settings, "CACHE_SLOW_REBUILD_MS", 500))
    data = _load()
    if error:
        data["rebuild_errors"] += 1
    else:
        data["rebuilds"] += 1
        data["total_rebuild_ms"] += float(rebuild_ms)
        data["rebuild_samples"] += 1
        if rebuild_ms > float(data.get("largest_rebuild_ms") or 0):
            data["largest_rebuild_ms"] = float(rebuild_ms)
        if rebuild_ms >= slow_ms:
            data["slow_rebuilds"] = int(data.get("slow_rebuilds") or 0) + 1
    _save(data)


def record_invalidation(count: int = 1) -> None:
    data = _load()
    data["invalidations"] += int(count)
    _save(data)


def record_lock_wait_timeout() -> None:
    data = _load()
    data["lock_wait_timeouts"] += 1
    _save(data)


def get_metrics_snapshot() -> dict[str, Any]:
    data = _load()
    hits = int(data["hits"])
    stale = int(data["stale_hits"])
    misses = int(data["misses"])
    total = hits + stale + misses
    hit_ratio = round(((hits + stale) / total) * 100, 2) if total else 0.0
    miss_ratio = round((misses / total) * 100, 2) if total else 0.0
    avg_lookup = (
        round(data["total_lookup_ms"] / data["lookup_samples"], 3)
        if data["lookup_samples"]
        else 0.0
    )
    avg_rebuild = (
        round(data["total_rebuild_ms"] / data["rebuild_samples"], 3)
        if data["rebuild_samples"]
        else 0.0
    )
    return {
        **data,
        "hit_ratio_pct": hit_ratio,
        "miss_ratio_pct": miss_ratio,
        "avg_lookup_ms": avg_lookup,
        "avg_rebuild_ms": avg_rebuild,
        "total_requests": total,
    }


def reset_metrics() -> None:
    _save(_default_metrics())


class Timer:
    def __init__(self):
        self._start = time.perf_counter()

    def ms(self) -> float:
        return (time.perf_counter() - self._start) * 1000.0
