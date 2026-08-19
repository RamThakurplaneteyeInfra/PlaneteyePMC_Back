"""
Lightweight, opt-in DPR request timing.

Enable with DPR_PERF_LOG=true. Logs a single [DPR PERF] line per request
with stage timings and SQL counts. Safe to leave in production (no-op when off).
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import contextmanager
from typing import Any

from django.conf import settings
from django.db import connection, reset_queries

logger = logging.getLogger("pmc.dpr.perf")


def perf_logging_enabled() -> bool:
    return bool(getattr(settings, "DPR_PERF_LOG", False))


class DprPerfTracker:
    def __init__(self, *, endpoint: str, method: str, request=None):
        self.endpoint = endpoint
        self.method = method
        self.request = request
        self.request_id = uuid.uuid4().hex[:12]
        self.stages: dict[str, float] = {}
        self.extra: dict[str, Any] = {}
        self._t0 = time.perf_counter()
        self._sql_start = 0
        self.sql_query_count = 0
        self._debug_sql = bool(getattr(settings, "DEBUG", False))
        if self._debug_sql:
            reset_queries()
            self._sql_start = len(connection.queries)

    def add(self, **kwargs: Any) -> None:
        self.extra.update(kwargs)

    @contextmanager
    def span(self, name: str):
        start = time.perf_counter()
        try:
            yield
        finally:
            self.stages[name] = round((time.perf_counter() - start) * 1000, 2)

    def finish(self) -> dict[str, Any]:
        if self._debug_sql:
            self.sql_query_count = max(0, len(connection.queries) - self._sql_start)
        total_ms = round((time.perf_counter() - self._t0) * 1000, 2)
        payload = {
            "request_id": self.request_id,
            "endpoint": self.endpoint,
            "method": self.method,
            "total_ms": total_ms,
            "sql_query_count": self.sql_query_count,
            **self.stages,
            **self.extra,
        }
        if self.request is not None:
            user = getattr(self.request, "user", None)
            payload.setdefault("user_id", getattr(user, "id", None))
        if perf_logging_enabled():
            logger.info("[DPR PERF] %s", payload)
        return payload


@contextmanager
def dpr_perf_request(request, endpoint: str):
    tracker = DprPerfTracker(
        endpoint=endpoint,
        method=getattr(request, "method", ""),
        request=request,
    )
    try:
        yield tracker
    finally:
        tracker.finish()
