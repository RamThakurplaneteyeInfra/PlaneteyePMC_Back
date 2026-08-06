"""
Production hardening for in-process DPR email ThreadPoolExecutor.

- Single global EMAIL_EXECUTOR
- Runtime metrics + snapshot for health API
- Graceful atexit shutdown
- Structured [DPR Email] logging helpers
"""

from __future__ import annotations

import atexit
import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

from django.conf import settings

logger = logging.getLogger("pmc.dpr.email")

_LOG_PREFIX = "[DPR Email]"

_DEFAULT_MAX_WORKERS = 4
_DEFAULT_MAX_PENDING = 200
_SLOW_EMAIL_SEC = 10.0

_init_lock = threading.Lock()
_shutdown_registered = False
_executor: ThreadPoolExecutor | None = None


@dataclass
class _EmailPoolMetrics:
    queued: int = 0
    running: int = 0
    completed: int = 0
    failed: int = 0
    skipped_duplicate: int = 0
    pending: int = 0  # queued but not yet started
    max_queue_depth: int = 0
    slow_emails: int = 0
    send_count: int = 0
    total_send_ms: float = 0.0
    total_processing_ms: float = 0.0
    total_queue_wait_ms: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def snapshot(self, *, max_workers: int, active_threads: int) -> dict[str, Any]:
        with self.lock:
            avg_send = (
                round(self.total_send_ms / self.send_count, 2) if self.send_count else 0.0
            )
            avg_total = (
                round(self.total_processing_ms / self.send_count, 2)
                if self.send_count
                else 0.0
            )
            avg_wait = (
                round(self.total_queue_wait_ms / self.queued, 2) if self.queued else 0.0
            )
            return {
                "max_workers": max_workers,
                "active_workers": active_threads,
                "queued_tasks": self.pending,
                "emails_queued": self.queued,
                "emails_running": self.running,
                "completed_tasks": self.completed,
                "failed_tasks": self.failed,
                "skipped_duplicate": self.skipped_duplicate,
                "max_queue_depth": self.max_queue_depth,
                "slow_emails": self.slow_emails,
                "avg_send_ms": avg_send,
                "avg_total_processing_ms": avg_total,
                "avg_queue_wait_ms": avg_wait,
            }


METRICS = _EmailPoolMetrics()


def _max_workers() -> int:
    try:
        return int(getattr(settings, "DPR_EMAIL_MAX_WORKERS", _DEFAULT_MAX_WORKERS))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_WORKERS


def _max_pending() -> int:
    try:
        return int(getattr(settings, "DPR_EMAIL_MAX_PENDING", _DEFAULT_MAX_PENDING))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_PENDING


def _slow_threshold_sec() -> float:
    try:
        return float(getattr(settings, "DPR_EMAIL_SLOW_SEC", _SLOW_EMAIL_SEC))
    except (TypeError, ValueError):
        return _SLOW_EMAIL_SEC


def _shutdown_executor() -> None:
    global _executor
    exe = _executor
    if exe is None:
        return
    logger.info("%s Shutting down executor (wait=True)", _LOG_PREFIX)
    try:
        # Drain in-flight SMTP; cancel_futures requires Python 3.9+
        exe.shutdown(wait=True, cancel_futures=False)
    except TypeError:
        exe.shutdown(wait=True)
    except Exception:
        logger.exception("%s Executor shutdown error", _LOG_PREFIX)
    finally:
        _executor = None


def get_email_executor() -> ThreadPoolExecutor:
    """Return the singleton executor (created once)."""
    global _executor, _shutdown_registered
    if _executor is not None:
        return _executor
    with _init_lock:
        if _executor is None:
            workers = _max_workers()
            _executor = ThreadPoolExecutor(
                max_workers=workers,
                thread_name_prefix="dpr-email",
            )
            if not _shutdown_registered:
                atexit.register(_shutdown_executor)
                _shutdown_registered = True
            logger.info(
                "%s Executor started max_workers=%s",
                _LOG_PREFIX,
                workers,
            )
        return _executor


# Eager singleton alias — import-safe; same object as get_email_executor()
EMAIL_EXECUTOR = get_email_executor()


def _active_thread_count() -> int:
    exe = _executor
    if exe is None:
        return 0
    threads = getattr(exe, "_threads", None) or set()
    return len(threads)


def get_email_pool_snapshot() -> dict[str, Any]:
    """Runtime metrics for /api/system/background-tasks/."""
    return {
        "thread_pool": METRICS.snapshot(
            max_workers=_max_workers(),
            active_threads=_active_thread_count(),
        )
    }


def mark_queued() -> float:
    """Record queue event; returns enqueue timestamp (perf_counter)."""
    now = time.perf_counter()
    with METRICS.lock:
        METRICS.queued += 1
        METRICS.pending += 1
        if METRICS.pending > METRICS.max_queue_depth:
            METRICS.max_queue_depth = METRICS.pending
    return now


def mark_started(enqueued_at: float | None) -> float:
    now = time.perf_counter()
    wait_ms = ((now - enqueued_at) * 1000.0) if enqueued_at else 0.0
    with METRICS.lock:
        if METRICS.pending > 0:
            METRICS.pending -= 1
        METRICS.running += 1
        METRICS.total_queue_wait_ms += wait_ms
    logger.info("%s Thread Started wait_ms=%.1f", _LOG_PREFIX, wait_ms)
    return now


def mark_finished(
    *,
    success: bool,
    started_at: float | None,
    send_ms: float = 0.0,
    duplicate: bool = False,
) -> None:
    now = time.perf_counter()
    total_ms = ((now - started_at) * 1000.0) if started_at else 0.0
    with METRICS.lock:
        if METRICS.running > 0:
            METRICS.running -= 1
        if duplicate:
            METRICS.skipped_duplicate += 1
        elif success:
            METRICS.completed += 1
            METRICS.send_count += 1
            METRICS.total_send_ms += send_ms
            METRICS.total_processing_ms += total_ms
            if total_ms >= _slow_threshold_sec() * 1000.0:
                METRICS.slow_emails += 1
                logger.warning(
                    "%s Slow email total_ms=%.1f threshold_sec=%s",
                    _LOG_PREFIX,
                    total_ms,
                    _slow_threshold_sec(),
                )
        else:
            METRICS.failed += 1
            METRICS.send_count += 1
            METRICS.total_send_ms += send_ms
            METRICS.total_processing_ms += total_ms


def submit_email_job(fn: Callable, kwargs: dict) -> Future | None:
    """
    Submit background email work. Never raises to the request thread.
    Returns Future when using the pool; None when running inline (tests)
    or when the pending queue is at capacity (job dropped + logged).
    """
    with METRICS.lock:
        pending_now = METRICS.pending
    if pending_now >= _max_pending():
        logger.error(
            "%s Queue full pending=%s max=%s — dropping fn=%s",
            _LOG_PREFIX,
            pending_now,
            _max_pending(),
            getattr(fn, "__name__", str(fn)),
        )
        with METRICS.lock:
            METRICS.failed += 1
        return None

    enqueued_at = mark_queued()
    inline = getattr(settings, "DPR_EMAIL_INLINE", False)

    def _runner():
        started_at = mark_started(enqueued_at)
        send_ms = 0.0
        success = False
        duplicate = False
        try:
            result = fn(**kwargs)
            status = (result or {}).get("status") if isinstance(result, dict) else None
            send_ms = float((result or {}).get("send_ms") or 0.0) if isinstance(result, dict) else 0.0
            if status == "skipped_duplicate":
                duplicate = True
                success = True
            elif status == "sent":
                success = True
            elif status in ("no_recipients", "dpr_not_found"):
                # Soft completion — not an SMTP failure
                success = True
            elif status == "failed":
                success = False
            else:
                success = True
        except Exception:
            success = False
            # Log keys only — avoid dumping email recipient payloads.
            logger.exception(
                "%s Unhandled background error fn=%s kwargs_keys=%s",
                _LOG_PREFIX,
                getattr(fn, "__name__", str(fn)),
                sorted(kwargs.keys()),
            )
        finally:
            mark_finished(
                success=success,
                started_at=started_at,
                send_ms=send_ms,
                duplicate=duplicate,
            )

    try:
        if inline:
            _runner()
            return None
        return EMAIL_EXECUTOR.submit(_runner)
    except Exception:
        logger.exception("%s Failed to submit email job", _LOG_PREFIX)
        # Undo pending if submit itself failed before runner started
        with METRICS.lock:
            if METRICS.pending > 0:
                METRICS.pending -= 1
            METRICS.failed += 1
        return None


def reset_metrics_for_tests() -> None:
    """Test helper — clears counters."""
    with METRICS.lock:
        METRICS.queued = 0
        METRICS.running = 0
        METRICS.completed = 0
        METRICS.failed = 0
        METRICS.skipped_duplicate = 0
        METRICS.pending = 0
        METRICS.max_queue_depth = 0
        METRICS.slow_emails = 0
        METRICS.send_count = 0
        METRICS.total_send_ms = 0.0
        METRICS.total_processing_ms = 0.0
        METRICS.total_queue_wait_ms = 0.0
