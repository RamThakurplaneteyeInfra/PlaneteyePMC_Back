"""
Background processing pipeline for TutorialVideo records.

Every accepted upload must end as ``ready`` or ``failed`` with a non-empty
``processing_error`` on failure — never forever-``processing``.
"""

from __future__ import annotations

import logging
import tempfile
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.business_audit import write_business_audit
from core.cache_keys import invalidate_list_cache
from core.models import BusinessAuditLog
from tutorial_videos.ffmpeg_service import (
    VideoProcessingError,
    ffmpeg_available,
    optimize_video,
)
from tutorial_videos.models import TutorialVideo

logger = logging.getLogger("pmc.tutorial_videos.processing")

CACHE_PREFIX = "tutorial_videos_list"


def invalidate_tutorial_caches() -> None:
    invalidate_list_cache(CACHE_PREFIX)
    invalidate_list_cache("tutorial_video_detail")


def max_processing_seconds() -> int:
    try:
        return max(60, int(getattr(settings, "TUTORIAL_VIDEO_MAX_PROCESSING_SEC", 900)))
    except (TypeError, ValueError):
        return 900


def mark_failed_by_id(video_id: int, message: str) -> None:
    try:
        video = TutorialVideo.objects.get(pk=video_id)
    except TutorialVideo.DoesNotExist:
        return
    if video.status == TutorialVideo.STATUS_READY and video.optimized_s3_key:
        return
    _mark_failed(video, message)


def _mark_failed(video: TutorialVideo, message: str, *, temp_key: str = "") -> None:
    """
    Mark processing failed with a human-readable error.

    Keep the temporary S3 object so reprocess can retry after infra fixes.
    """
    safe = (message or "Video processing failed.").strip()[:500] or "Video processing failed."
    try:
        video.refresh_from_db()
    except TutorialVideo.DoesNotExist:
        return

    if video.status == TutorialVideo.STATUS_READY and video.optimized_s3_key:
        return

    if temp_key and not (video.temp_s3_key or "").strip():
        video.temp_s3_key = temp_key

    video.status = TutorialVideo.STATUS_FAILED
    video.processing_error = safe
    video.save(
        update_fields=["status", "processing_error", "temp_s3_key", "updated_at"]
    )

    invalidate_tutorial_caches()
    write_business_audit(
        entity_type=BusinessAuditLog.ENTITY_TUTORIAL_VIDEO,
        action=BusinessAuditLog.ACTION_FAILED,
        actor=video.created_by,
        entity_id=video.pk,
        detail=(
            f"Tutorial video processing failed title={video.title!r} "
            f"section={getattr(video, 'section', '')}"
        ),
    )
    logger.warning(
        "tutorial_video_failed id=%s section=%s reason=%s",
        video.pk,
        getattr(video, "section", ""),
        safe,
    )


def fail_stuck_processing(*, max_age_sec: int | None = None) -> int:
    """
    Mark stale ``processing`` rows as failed (worker crash / OOM / lost job).
    Cheap DB update — safe to call from list/detail GETs.
    """
    age = max_age_sec if max_age_sec is not None else max_processing_seconds()
    cutoff = timezone.now() - timedelta(seconds=age)
    qs = TutorialVideo.objects.filter(
        status=TutorialVideo.STATUS_PROCESSING,
        is_active=True,
        updated_at__lt=cutoff,
    ).only("id", "title", "section", "status", "temp_s3_key", "created_by_id", "updated_at")
    count = 0
    msg = f"Processing timed out after {max(1, age // 60)} minutes."
    for video in qs.iterator(chunk_size=50):
        _mark_failed(video, msg)
        count += 1
    if count:
        logger.warning("tutorial_stuck_sweep marked_failed=%s cutoff=%s", count, cutoff)
    return count


def maybe_fail_if_stuck(video: TutorialVideo) -> TutorialVideo:
    """If a single row has been processing too long, mark failed and refresh."""
    if video.status != TutorialVideo.STATUS_PROCESSING:
        return video
    age = (timezone.now() - video.updated_at).total_seconds()
    if age < max_processing_seconds():
        return video
    _mark_failed(
        video,
        f"Processing timed out after {max(1, max_processing_seconds() // 60)} minutes.",
    )
    video.refresh_from_db()
    return video


def process_tutorial_video(*, video_id: int) -> None:
    """
    Download temporary S3 object → FFmpeg optimize → upload optimized → cleanup.
    Safe to call from a worker thread or Celery worker.
    """
    from services import s3_tutorial_videos as s3

    try:
        video = TutorialVideo.objects.get(pk=video_id)
    except TutorialVideo.DoesNotExist:
        logger.warning("Tutorial video %s missing; skip processing", video_id)
        return

    if not video.is_active or video.status == TutorialVideo.STATUS_DELETED:
        logger.info("Tutorial video %s inactive/deleted; skip", video_id)
        return

    if video.status == TutorialVideo.STATUS_READY and video.optimized_s3_key:
        logger.info("Tutorial video %s already ready; skip", video_id)
        return

    # Heartbeat so stuck-sweeper does not race an active job immediately.
    video.status = TutorialVideo.STATUS_PROCESSING
    video.processing_error = ""
    video.save(update_fields=["status", "processing_error", "updated_at"])

    if not ffmpeg_available():
        _mark_failed(video, "ffmpeg not available on worker")
        return

    temp_key = (video.temp_s3_key or "").strip()
    if not temp_key:
        _mark_failed(video, "Temporary upload is missing.")
        return

    logger.info(
        "Processing started video_id=%s section=%s original_size=%s key=%s",
        video_id,
        getattr(video, "section", ""),
        video.original_file_size,
        temp_key,
    )

    tmp_dir = tempfile.mkdtemp(prefix="tutorial_video_")
    source_path = Path(tmp_dir) / "source"
    output_path = Path(tmp_dir) / "optimized.mp4"
    optimized_key = None

    try:
        ext = Path(temp_key).suffix or ".mp4"
        source_path = Path(tmp_dir) / f"source{ext}"

        try:
            s3.download_to_path(temp_key, str(source_path))
        except Exception as exc:
            logger.exception("S3 download failed video_id=%s", video_id)
            _mark_failed(
                video,
                f"S3 download failed: {type(exc).__name__}",
                temp_key=temp_key,
            )
            return

        if not source_path.is_file() or source_path.stat().st_size <= 0:
            _mark_failed(video, "Invalid or corrupt video file", temp_key=temp_key)
            return

        try:
            result = optimize_video(source_path, output_path)
        except VideoProcessingError as exc:
            logger.warning("FFmpeg failed video_id=%s reason=%s", video_id, exc)
            _mark_failed(video, str(exc) or "Invalid or corrupt video file", temp_key=temp_key)
            return

        optimized_key = s3.build_optimized_key()
        s3_started = __import__("time").perf_counter()
        try:
            opt_size = s3.upload_local_file(
                local_path=str(output_path),
                s3_key=optimized_key,
                content_type="video/mp4",
                metadata={
                    "tutorial-video-id": str(video_id),
                    "title": (video.title or "")[:80],
                },
            )
        except Exception as exc:
            logger.exception("S3 optimized upload failed video_id=%s", video_id)
            s3.delete_object(optimized_key)
            _mark_failed(
                video,
                f"S3 upload failed: {type(exc).__name__}",
                temp_key=temp_key,
            )
            return
        s3_ms = int((__import__("time").perf_counter() - s3_started) * 1000)

        original_size = int(video.original_file_size or 0)
        ratio = None
        if original_size > 0 and opt_size > 0:
            ratio = round(original_size / opt_size, 3)

        video.status = TutorialVideo.STATUS_READY
        video.processing_error = ""
        video.optimized_s3_key = optimized_key
        video.video_url = s3.object_url(optimized_key)
        video.file_size = opt_size
        video.duration_seconds = result.duration or None
        video.width = result.width
        video.height = result.height
        video.compression_ratio = ratio
        video.processing_ms = result.processing_ms
        video.temp_s3_key = ""
        video.save(
            update_fields=[
                "status",
                "processing_error",
                "optimized_s3_key",
                "video_url",
                "file_size",
                "duration_seconds",
                "width",
                "height",
                "compression_ratio",
                "processing_ms",
                "temp_s3_key",
                "updated_at",
            ]
        )

        s3.delete_object(temp_key)

        invalidate_tutorial_caches()
        write_business_audit(
            entity_type=BusinessAuditLog.ENTITY_TUTORIAL_VIDEO,
            action=BusinessAuditLog.ACTION_COMPLETED,
            actor=video.created_by,
            entity_id=video.pk,
            detail=(
                f"Tutorial video processed title={video.title!r} "
                f"section={video.section} "
                f"original={original_size} optimized={opt_size} "
                f"ratio={ratio} ffmpeg_ms={result.processing_ms} s3_ms={s3_ms}"
            ),
        )
        logger.info(
            "Processing completed video_id=%s original=%s optimized=%s ratio=%s ffmpeg_ms=%s s3_ms=%s",
            video_id,
            original_size,
            opt_size,
            ratio,
            result.processing_ms,
            s3_ms,
        )
    except Exception:
        logger.exception("Processing failed video_id=%s", video_id)
        if optimized_key:
            s3.delete_object(optimized_key)
        _mark_failed(video, "Video processing failed.", temp_key=temp_key)
    finally:
        _cleanup_dir(tmp_dir)


def _cleanup_dir(path: str) -> None:
    import shutil

    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception:
        logger.exception("Failed to cleanup temp dir")


def soft_delete_tutorial_video(video: TutorialVideo) -> None:
    """Soft-delete and remove S3 objects."""
    from services import s3_tutorial_videos as s3

    opt = (video.optimized_s3_key or "").strip()
    tmp = (video.temp_s3_key or "").strip()
    if opt:
        s3.delete_object(opt)
    if tmp:
        s3.delete_object(tmp)

    video.is_active = False
    video.status = TutorialVideo.STATUS_DELETED
    video.optimized_s3_key = ""
    video.temp_s3_key = ""
    video.video_url = ""
    video.save(
        update_fields=[
            "is_active",
            "status",
            "optimized_s3_key",
            "temp_s3_key",
            "video_url",
            "updated_at",
        ]
    )
    invalidate_tutorial_caches()


def _celery_usable() -> bool:
    """True only when explicitly enabled (requires a running Celery worker)."""
    return bool(getattr(settings, "TUTORIAL_VIDEO_USE_CELERY", False))


def enqueue_tutorial_processing(video_id: int) -> None:
    """
    Enqueue processing. Prefer Celery when usable; else in-process ThreadPool.
    Always marks failed if enqueue itself cannot start work.
    """
    from tutorial_videos.exceptions import TutorialVideoQueueFull
    from tutorial_videos.ffmpeg_service import ffmpeg_available
    from tutorial_videos.video_executor import submit_video_job

    if not ffmpeg_available():
        mark_failed_by_id(int(video_id), "ffmpeg not available on worker")
        return

    if _celery_usable():
        try:
            from tutorial_videos.tasks import process_tutorial_video_task

            process_tutorial_video_task.delay(int(video_id))
            logger.info("tutorial_enqueued_celery video_id=%s", video_id)
            return
        except Exception:
            logger.exception(
                "Celery enqueue failed video_id=%s; falling back to ThreadPool",
                video_id,
            )

    try:
        future = submit_video_job(process_tutorial_video, video_id=int(video_id))
        inline = getattr(settings, "TUTORIAL_VIDEO_INLINE", False)
        if future is None and not inline:
            # submit_video_job returns None on hard submit failure (not inline).
            # Distinguishing: when inline, runner already executed.
            # Re-check: if still processing and submit returned None without inline → fail.
            still = TutorialVideo.objects.filter(
                pk=video_id, status=TutorialVideo.STATUS_PROCESSING
            ).exists()
            if still:
                # Could be race; give ThreadPool another chance via direct call log
                logger.error("ThreadPool submit returned None video_id=%s", video_id)
                mark_failed_by_id(
                    int(video_id),
                    "Failed to queue video processing job.",
                )
        else:
            logger.info(
                "tutorial_enqueued_threadpool video_id=%s inline=%s",
                video_id,
                inline,
            )
    except TutorialVideoQueueFull:
        mark_failed_by_id(int(video_id), "Video processing queue is full.")
    except Exception:
        logger.exception("Enqueue failed video_id=%s", video_id)
        mark_failed_by_id(int(video_id), "Failed to queue video processing job.")


def queue_processing_after_commit(video_id: int) -> None:
    """Schedule processing after the DB transaction commits."""

    def _enqueue():
        enqueue_tutorial_processing(int(video_id))

    transaction.on_commit(_enqueue)
