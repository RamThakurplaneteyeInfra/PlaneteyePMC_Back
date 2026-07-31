"""
Query profiling helpers for cached endpoints.

Use around expensive builders to log DB query count / duration before cache
fills, and to spot regressions after caching is enabled.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

from django.conf import settings
from django.db import connection, reset_queries

logger = logging.getLogger("pmc.cache.profile")

# Log when a rebuild exceeds this many ms (override via settings).
SLOW_REBUILD_MS = float(getattr(settings, "CACHE_SLOW_REBUILD_MS", 500))


@dataclass
class QueryProfile:
    label: str
    duration_ms: float = 0.0
    query_count: int = 0
    rows_hint: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "duration_ms": round(self.duration_ms, 3),
            "query_count": self.query_count,
            "rows_hint": self.rows_hint,
            **self.extra,
        }


@contextmanager
def profile_queries(label: str, *, rows_hint: int | None = None) -> Iterator[QueryProfile]:
    """
    Measure wall time and (when DEBUG) SQL query count for a block.

    Example::

        with profile_queries("project_overview") as prof:
            payload = expensive()
        # prof.query_count / prof.duration_ms available; slow ops are logged.
    """
    debug = bool(getattr(settings, "DEBUG", False))
    if debug:
        reset_queries()
    profile = QueryProfile(label=label, rows_hint=rows_hint)
    t0 = time.perf_counter()
    try:
        yield profile
    finally:
        profile.duration_ms = (time.perf_counter() - t0) * 1000.0
        if debug:
            try:
                profile.query_count = len(connection.queries)
            except Exception:
                profile.query_count = 0
        if profile.duration_ms >= SLOW_REBUILD_MS:
            logger.warning(
                "slow_cache_rebuild label=%s duration_ms=%.1f queries=%s rows=%s",
                label,
                profile.duration_ms,
                profile.query_count,
                profile.rows_hint,
            )
        else:
            logger.debug(
                "cache_rebuild_profile label=%s duration_ms=%.1f queries=%s",
                label,
                profile.duration_ms,
                profile.query_count,
            )
