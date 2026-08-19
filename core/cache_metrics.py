"""
Cache hit/miss/rebuild/invalidation counters.

Writes are applied in-process first so DPR/API requests do not pay Redis
GET+SET (~500 ms at ~250 ms RTT) for observability. Redis is updated in
the background; health snapshots flush pending deltas first.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger("pmc.cache.metrics")

_METRICS_KEY = "_pmc:cache_metrics:v1"
_LOCK_KEY = "_pmc:cache_metrics:lock"

_lock = threading.Lock()
_deltas: dict[str, Any] | None = None
_dirty = False
_flush_scheduled = False


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


def _ensure_deltas() -> dict[str, Any]:
    global _deltas
    if _deltas is None:
        _deltas = _default_metrics()
    return _deltas


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


def _merge(base: dict[str, Any], delta: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in delta.items():
        if key == "largest_rebuild_ms":
            out[key] = max(float(out.get(key) or 0), float(value or 0))
        elif isinstance(value, (int, float)):
            out[key] = type(out.get(key, value))(out.get(key, 0) + value)
        else:
            out[key] = value
    return out


def flush_metrics(*, force: bool = False) -> None:
    """Push in-process deltas to the cache backend (Redis or LocMem)."""
    global _deltas, _dirty, _flush_scheduled
    with _lock:
        if not _dirty and not force:
            _flush_scheduled = False
            return
        delta = dict(_ensure_deltas())
        _deltas = _default_metrics()
        _dirty = False
        _flush_scheduled = False
    if all(
        (v == 0 or v == 0.0)
        for k, v in delta.items()
        if k != "largest_rebuild_ms"
    ) and not delta.get("largest_rebuild_ms"):
        return
    data = _merge(_load(), delta)
    _save(data)


def _schedule_flush() -> None:
    global _flush_scheduled
    if getattr(settings, "CACHE_METRICS_INLINE", False):
        flush_metrics()
        return
    with _lock:
        if _flush_scheduled:
            return
        _flush_scheduled = True
    timer = threading.Timer(0.05, _safe_flush)
    timer.daemon = True
    timer.start()


def _safe_flush() -> None:
    try:
        flush_metrics()
    except Exception as exc:
        logger.debug("metrics flush failed: %s", exc)


def _record(mutator: Callable[[dict[str, Any]], None]) -> None:
    global _dirty
    with _lock:
        mutator(_ensure_deltas())
        _dirty = True
    _schedule_flush()


def record_hit(*, stale: bool = False, lookup_ms: float = 0.0) -> None:
    def mut(data: dict[str, Any]) -> None:
        if stale:
            data["stale_hits"] += 1
        else:
            data["hits"] += 1
        data["total_lookup_ms"] += float(lookup_ms)
        data["lookup_samples"] += 1

    _record(mut)


def record_miss(*, lookup_ms: float = 0.0) -> None:
    def mut(data: dict[str, Any]) -> None:
        data["misses"] += 1
        data["total_lookup_ms"] += float(lookup_ms)
        data["lookup_samples"] += 1

    _record(mut)


def record_rebuild(*, rebuild_ms: float = 0.0, error: bool = False) -> None:
    slow_ms = float(getattr(settings, "CACHE_SLOW_REBUILD_MS", 500))

    def mut(data: dict[str, Any]) -> None:
        if error:
            data["rebuild_errors"] += 1
            return
        data["rebuilds"] += 1
        data["total_rebuild_ms"] += float(rebuild_ms)
        data["rebuild_samples"] += 1
        if rebuild_ms > float(data.get("largest_rebuild_ms") or 0):
            data["largest_rebuild_ms"] = float(rebuild_ms)
        if rebuild_ms >= slow_ms:
            data["slow_rebuilds"] = int(data.get("slow_rebuilds") or 0) + 1

    _record(mut)


def record_invalidation(count: int = 1) -> None:
    def mut(data: dict[str, Any]) -> None:
        data["invalidations"] += int(count)

    _record(mut)


def record_lock_wait_timeout() -> None:
    def mut(data: dict[str, Any]) -> None:
        data["lock_wait_timeouts"] += 1

    _record(mut)


def get_metrics_snapshot() -> dict[str, Any]:
    flush_metrics(force=True)
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
    global _deltas, _dirty
    with _lock:
        _deltas = _default_metrics()
        _dirty = False
    _save(_default_metrics())


class Timer:
    def __init__(self):
        self._start = time.perf_counter()

    def ms(self) -> float:
        return (time.perf_counter() - self._start) * 1000.0
