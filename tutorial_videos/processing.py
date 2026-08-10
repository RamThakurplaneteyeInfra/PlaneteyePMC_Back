"""
Background processing pipeline for TutorialVideo records.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from django.db import transaction

from core.business_audit import write_business_audit
from core.cache_keys import invalidate_list_cache
from core.models import BusinessAuditLog
from tutorial_videos.ffmpeg_service import VideoProcessingError, optimize_video
from tutorial_videos.models import TutorialVideo

logger = logging.getLogger("pmc.tutorial_videos.processing")

CACHE_PREFIX = "tutorial_videos_list"


def invalidate_tutorial_caches() -> None:
    invalidate_list_cache(CACHE_PREFIX)
    invalidate_list_cache("tutorial_video_detail")


def process_tutorial_video(*, video_id: int) -> None:
    """
    Download temporary S3 object → FFmpeg optimize → upload optimized → cleanup.
    Safe to call from a worker thread.
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

    temp_key = (video.temp_s3_key or "").strip()
    if not temp_key:
        _mark_failed(video, "Temporary upload is missing.")
        return

    logger.info(
        "Processing started video_id=%s original_size=%s",
        video_id,
        video.original_file_size,
    )

    tmp_dir = tempfile.mkdtemp(prefix="tutorial_video_")
    source_path = Path(tmp_dir) / "source"
    output_path = Path(tmp_dir) / "optimized.mp4"
    optimized_key = None

    try:
        # Preserve extension for ffmpeg container sniffing.
        ext = Path(temp_key).suffix or ".mp4"
        source_path = Path(tmp_dir) / f"source{ext}"

        s3.download_to_path(temp_key, str(source_path))
        result = optimize_video(source_path, output_path)

        optimized_key = s3.build_optimized_key()
        s3_started = __import__("time").perf_counter()
        opt_size = s3.upload_local_file(
            local_path=str(output_path),
            s3_key=optimized_key,
            content_type="video/mp4",
            metadata={
                "tutorial-video-id": str(video_id),
                "title": (video.title or "")[:80],
            },
        )
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

        # Delete temporary original after DB update succeeds.
        s3.delete_object(temp_key)

        invalidate_tutorial_caches()
        write_business_audit(
            entity_type=BusinessAuditLog.ENTITY_TUTORIAL_VIDEO,
            action=BusinessAuditLog.ACTION_COMPLETED,
            actor=video.created_by,
            entity_id=video.pk,
            detail=(
                f"Tutorial video processed title={video.title!r} "
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
    except VideoProcessingError as exc:
        logger.warning("Processing failed video_id=%s reason=%s", video_id, exc)
        if optimized_key:
            s3.delete_object(optimized_key)
        _mark_failed(video, str(exc), temp_key=temp_key)
    except Exception:
        logger.exception("Processing failed video_id=%s", video_id)
        if optimized_key:
            s3.delete_object(optimized_key)
        _mark_failed(video, "Video processing failed.", temp_key=temp_key)
    finally:
        _cleanup_dir(tmp_dir)


def _mark_failed(video: TutorialVideo, message: str, *, temp_key: str = "") -> None:
    from services import s3_tutorial_videos as s3

    safe = (message or "Video processing failed.")[:500]
    try:
        video.refresh_from_db()
    except TutorialVideo.DoesNotExist:
        return

    video.status = TutorialVideo.STATUS_FAILED
    video.processing_error = safe
    # Drop temp object on failure to avoid storage leaks.
    key = temp_key or video.temp_s3_key
    video.temp_s3_key = ""
    video.save(
        update_fields=["status", "processing_error", "temp_s3_key", "updated_at"]
    )
    if key:
        s3.delete_object(key)

    invalidate_tutorial_caches()
    write_business_audit(
        entity_type=BusinessAuditLog.ENTITY_TUTORIAL_VIDEO,
        action=BusinessAuditLog.ACTION_FAILED,
        actor=video.created_by,
        entity_id=video.pk,
        detail=f"Tutorial video processing failed title={video.title!r}",
    )


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


def queue_processing_after_commit(video_id: int) -> None:
    """Schedule process_tutorial_video after the DB transaction commits."""

    def _enqueue():
        from tutorial_videos.exceptions import TutorialVideoQueueFull
        from tutorial_videos.video_executor import submit_video_job

        try:
            submit_video_job(process_tutorial_video, video_id=video_id)
        except TutorialVideoQueueFull:
            try:
                video = TutorialVideo.objects.get(pk=video_id)
            except TutorialVideo.DoesNotExist:
                return
            _mark_failed(video, "Video processing queue is full.")

    transaction.on_commit(_enqueue)
