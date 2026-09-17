"""
In-process ThreadPool for tutorial video FFmpeg jobs.

Mirrors dpr.email_executor: bounded workers, pending queue cap, inline mode for tests.
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

logger = logging.getLogger("pmc.tutorial_videos.executor")

_LOG_PREFIX = "[Tutorial Video]"
_DEFAULT_MAX_WORKERS = 1
_DEFAULT_MAX_PENDING = 20

_init_lock = threading.Lock()
_shutdown_registered = False
_executor: ThreadPoolExecutor | None = None


@dataclass
class _PoolMetrics:
    queued: int = 0
    running: int = 0
    completed: int = 0
    failed: int = 0
    pending: int = 0
    max_queue_depth: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def snapshot(self, *, max_workers: int, active_threads: int) -> dict[str, Any]:
        with self.lock:
            return {
                "max_workers": max_workers,
                "active_workers": active_threads,
                "queued_tasks": self.pending,
                "completed_tasks": self.completed,
                "failed_tasks": self.failed,
                "max_queue_depth": self.max_queue_depth,
            }


METRICS = _PoolMetrics()


def _max_workers() -> int:
    try:
        return max(1, int(getattr(settings, "TUTORIAL_VIDEO_MAX_WORKERS", _DEFAULT_MAX_WORKERS)))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_WORKERS


def _max_pending() -> int:
    try:
        return max(1, int(getattr(settings, "TUTORIAL_VIDEO_MAX_PENDING", _DEFAULT_MAX_PENDING)))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_PENDING


def _shutdown_executor() -> None:
    global _executor
    exe = _executor
    if exe is None:
        return
    logger.info("%s Shutting down executor (wait=True)", _LOG_PREFIX)
    try:
        exe.shutdown(wait=True, cancel_futures=False)
    except TypeError:
        exe.shutdown(wait=True)
    except Exception:
        logger.exception("%s Executor shutdown error", _LOG_PREFIX)
    finally:
        _executor = None


def get_video_executor() -> ThreadPoolExecutor:
    global _executor, _shutdown_registered
    if _executor is not None:
        return _executor
    with _init_lock:
        if _executor is None:
            workers = _max_workers()
            _executor = ThreadPoolExecutor(
                max_workers=workers,
                thread_name_prefix="tutorial-video",
            )
            if not _shutdown_registered:
                atexit.register(_shutdown_executor)
                _shutdown_registered = True
            logger.info("%s Executor started max_workers=%s", _LOG_PREFIX, workers)
        return _executor


VIDEO_EXECUTOR = None  # set lazily via get_video_executor in apps.ready / submit


def _active_thread_count() -> int:
    exe = _executor
    if exe is None:
        return 0
    threads = getattr(exe, "_threads", None) or set()
    return len(threads)


def get_video_pool_snapshot() -> dict[str, Any]:
    return {
        "thread_pool": METRICS.snapshot(
            max_workers=_max_workers(),
            active_threads=_active_thread_count(),
        )
    }


def pending_count() -> int:
    with METRICS.lock:
        return METRICS.pending


def queue_is_full() -> bool:
    return pending_count() >= _max_pending()


def mark_queued() -> float:
    now = time.perf_counter()
    with METRICS.lock:
        METRICS.queued += 1
        METRICS.pending += 1
        if METRICS.pending > METRICS.max_queue_depth:
            METRICS.max_queue_depth = METRICS.pending
    return now


def mark_started(enqueued_at: float | None) -> float:
    now = time.perf_counter()
    with METRICS.lock:
        if METRICS.pending > 0:
            METRICS.pending -= 1
        METRICS.running += 1
    wait_ms = ((now - enqueued_at) * 1000.0) if enqueued_at else 0.0
    logger.info("%s Processing started wait_ms=%.1f", _LOG_PREFIX, wait_ms)
    return now


def mark_finished(*, success: bool) -> None:
    with METRICS.lock:
        if METRICS.running > 0:
            METRICS.running -= 1
        if success:
            METRICS.completed += 1
        else:
            METRICS.failed += 1


def submit_video_job(fn: Callable, *, video_id: int) -> Future | None:
    """
    Queue background processing for a TutorialVideo pk.
    Returns Future when using the pool; None when running inline (tests)
    or when submit fails.
    Raises QueueFullError when pending queue is at capacity.
    """
    if queue_is_full():
        from tutorial_videos.exceptions import TutorialVideoQueueFull

        raise TutorialVideoQueueFull(
            f"Video processing queue is full (max {_max_pending()})."
        )

    enqueued_at = mark_queued()
    inline = getattr(settings, "TUTORIAL_VIDEO_INLINE", False)

    def _runner():
        from django.db import close_old_connections

        close_old_connections()
        started_at = mark_started(enqueued_at)
        success = False
        try:
            fn(video_id=video_id)
            success = True
        except Exception:
            success = False
            logger.exception(
                "%s Unhandled background error video_id=%s",
                _LOG_PREFIX,
                video_id,
            )
            try:
                from tutorial_videos.processing import mark_failed_by_id

                mark_failed_by_id(int(video_id), "Video processing failed.")
            except Exception:
                logger.exception(
                    "%s Failed to mark video failed video_id=%s",
                    _LOG_PREFIX,
                    video_id,
                )
        finally:
            mark_finished(success=success)
            close_old_connections()
            _ = started_at

    try:
        if inline:
            _runner()
            return None
        return get_video_executor().submit(_runner)
    except Exception:
        logger.exception("%s Failed to submit video job video_id=%s", _LOG_PREFIX, video_id)
        with METRICS.lock:
            if METRICS.pending > 0:
                METRICS.pending -= 1
            METRICS.failed += 1
        return None


def reset_metrics_for_tests() -> None:
    with METRICS.lock:
        METRICS.queued = 0
        METRICS.running = 0
        METRICS.completed = 0
        METRICS.failed = 0
        METRICS.pending = 0
        METRICS.max_queue_depth = 0
