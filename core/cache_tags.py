"""
Tag-based and batch cache invalidation on top of versioned RBAC prefixes.

Preserves existing ``invalidate_list_cache`` / version counters — tags map to
one or more prefixes that are version-bumped (old keys expire naturally).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable
from contextlib import contextmanager
from typing import Iterator

from core.cache_keys import invalidate_list_cache
from core.cache_metrics import record_invalidation

logger = logging.getLogger("pmc.cache.tags")

# Logical groups → existing cache prefixes (backward compatible).
CACHE_TAG_PREFIXES: dict[str, tuple[str, ...]] = {
    "overview": ("project_overview_v2",),
    "dropdown": ("projects_dropdown",),
    "projects": ("project_overview_v2", "projects_dropdown"),
    "dashboard": (
        "cashflow_dashboard",
        "cost_performance_dashboard",
        "equipment_dashboard",
        "manpower_dashboard",
        "bottlenecks_summary",
    ),
    "reports": (
        "contracts_summary",
        "contracts_list",
        "dpr_list",
        "dpr_pending_approval",
        "dpr_rejected",
        "project_quality_status_list",
        "health_safety_reports",
        "correspondence_list",
    ),
    "statistics": ("bottlenecks_summary", "budget_performance_list"),
    "bottlenecks": ("bottlenecks_summary", "project_overview_v2"),
    "invoicing": ("invoicing_list",),
    "cashflow": ("cashflow_list", "cashflow_dashboard"),
    "equipment": ("equipment_list", "equipment_dashboard"),
    "manpower": ("manpower_list", "manpower_dashboard"),
}

_local = threading.local()


def prefixes_for_tags(tags: Iterable[str]) -> list[str]:
    prefixes: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        for prefix in CACHE_TAG_PREFIXES.get(str(tag), ()):
            if prefix not in seen:
                seen.add(prefix)
                prefixes.append(prefix)
        # Allow passing a raw prefix as a "tag"
        raw = str(tag)
        if raw not in CACHE_TAG_PREFIXES and raw not in seen:
            seen.add(raw)
            prefixes.append(raw)
    return prefixes


def invalidate_tags(*tags: str) -> list[str]:
    """
    Invalidate logical cache groups by bumping prefix versions.

    Returns the list of prefixes touched.
    """
    if getattr(_local, "batch_active", False):
        pending = getattr(_local, "pending_tags", set())
        pending.update(str(t) for t in tags if t)
        _local.pending_tags = pending
        return []

    prefixes = prefixes_for_tags(tags)
    for prefix in prefixes:
        invalidate_list_cache(prefix)
    if prefixes:
        record_invalidation(len(prefixes))
        logger.info("cache_tag_invalidate tags=%s prefixes=%s", tags, prefixes)
    return prefixes


@contextmanager
def batch_cache_invalidation() -> Iterator[None]:
    """
    Coalesce invalidations inside a bulk write transaction.

    Usage::

        with batch_cache_invalidation():
            for row in rows:
                row.save()  # signals call invalidate_tags(...)
        # single flush at exit
    """
    prior = getattr(_local, "batch_active", False)
    prior_tags = getattr(_local, "pending_tags", set())
    _local.batch_active = True
    _local.pending_tags = set()
    try:
        yield
    finally:
        tags = list(getattr(_local, "pending_tags", set()))
        _local.batch_active = prior
        _local.pending_tags = prior_tags
        if tags:
            invalidate_tags(*tags)
