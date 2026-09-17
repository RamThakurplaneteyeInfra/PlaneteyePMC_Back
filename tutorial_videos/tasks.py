"""
Celery task for durable tutorial-video processing.

Prefer this when a Celery worker is running (Railway worker service).
Falls back to in-process ThreadPool when Celery is unavailable/eager.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.db import close_old_connections

logger = logging.getLogger("pmc.tutorial_videos.tasks")


@shared_task(
    bind=True,
    name="tutorial_videos.process_tutorial_video",
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=15 * 60,
    time_limit=16 * 60,
    max_retries=1,
)
def process_tutorial_video_task(self, video_id: int) -> dict:
    """
    Run FFmpeg optimize + S3 upload for one TutorialVideo.
    Always leaves the row as ready or failed (never silent).
    """
    close_old_connections()
    try:
        from tutorial_videos.processing import process_tutorial_video

        logger.info("celery_tutorial_process_start video_id=%s", video_id)
        process_tutorial_video(video_id=int(video_id))
        return {"video_id": int(video_id), "ok": True}
    except Exception as exc:
        # Soft/hard time limits and unexpected crashes — ensure DB reflects failure.
        logger.exception("celery_tutorial_process_error video_id=%s", video_id)
        try:
            from tutorial_videos.models import TutorialVideo
            from tutorial_videos.processing import mark_failed_by_id

            msg = "Processing timed out after 15 minutes."
            if "SoftTimeLimitExceeded" in type(exc).__name__ or "TimeLimitExceeded" in type(exc).__name__:
                msg = "Processing timed out after 15 minutes."
            elif str(exc):
                msg = "Video processing failed."
            mark_failed_by_id(int(video_id), msg)
        except Exception:
            logger.exception("celery_tutorial_mark_failed_error video_id=%s", video_id)
        return {"video_id": int(video_id), "ok": False}
    finally:
        close_old_connections()
