"""
Dedicated in-process ThreadPool for MPR PDF/Excel generation.

Mirrors tutorial_videos.video_executor / dpr.email_executor patterns.
Does NOT share the DPR email executor.
"""

from __future__ import annotations

import atexit
import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable

from django.conf import settings

logger = logging.getLogger("pmc.mpr.executor")

_init_lock = threading.Lock()
_shutdown_registered = False
_executor: ThreadPoolExecutor | None = None


def _max_workers() -> int:
    try:
        return max(1, int(getattr(settings, "MPR_MAX_WORKERS", 1)))
    except (TypeError, ValueError):
        return 1


def _inline_mode() -> bool:
    return bool(getattr(settings, "MPR_GENERATION_INLINE", False))


def _shutdown_executor() -> None:
    global _executor
    exe = _executor
    if exe is None:
        return
    try:
        exe.shutdown(wait=True, cancel_futures=False)
    except TypeError:
        exe.shutdown(wait=True)
    except Exception:
        logger.exception("MPR executor shutdown error")
    _executor = None


def get_mpr_executor() -> ThreadPoolExecutor:
    global _executor, _shutdown_registered
    if _executor is not None:
        return _executor
    with _init_lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(
                max_workers=_max_workers(),
                thread_name_prefix="mpr-gen",
            )
            if not _shutdown_registered:
                atexit.register(_shutdown_executor)
                _shutdown_registered = True
    return _executor


def submit_mpr_job(fn: Callable, *args, **kwargs) -> Future | None:
    """
    Submit generation work. In inline/test mode runs synchronously.
    Returns Future or None when run inline.
    """
    if _inline_mode():
        fn(*args, **kwargs)
        return None
    exe = get_mpr_executor()
    return exe.submit(fn, *args, **kwargs)
