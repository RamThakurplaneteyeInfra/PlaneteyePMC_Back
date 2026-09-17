"""
Manage stuck / failed tutorial video processing.

Examples:
  python manage.py tutorial_videos_process --sweep
  python manage.py tutorial_videos_process --reprocess 7
  python manage.py tutorial_videos_process --fail-stuck --max-age-sec 60
  python manage.py tutorial_videos_process --reprocess-all-failed
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from tutorial_videos.models import TutorialVideo
from tutorial_videos.processing import (
    enqueue_tutorial_processing,
    fail_stuck_processing,
    mark_failed_by_id,
)


class Command(BaseCommand):
    help = "Sweep stuck tutorial videos or re-queue processing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--sweep",
            action="store_true",
            help="Mark stale processing rows as failed (uses TUTORIAL_VIDEO_MAX_PROCESSING_SEC).",
        )
        parser.add_argument(
            "--fail-stuck",
            action="store_true",
            help="Alias for --sweep.",
        )
        parser.add_argument(
            "--max-age-sec",
            type=int,
            default=None,
            help="Override stuck age in seconds for --sweep.",
        )
        parser.add_argument(
            "--reprocess",
            type=int,
            default=None,
            help="Re-queue a single TutorialVideo id (requires temp_s3_key).",
        )
        parser.add_argument(
            "--reprocess-all-failed",
            action="store_true",
            help="Re-queue all failed active videos that still have temp_s3_key.",
        )
        parser.add_argument(
            "--mark-failed",
            type=int,
            default=None,
            help="Force-mark a video id as failed with a timeout message.",
        )

    def handle(self, *args, **options):
        if options["sweep"] or options["fail_stuck"]:
            n = fail_stuck_processing(max_age_sec=options["max_age_sec"])
            self.stdout.write(self.style.SUCCESS(f"Marked {n} stuck video(s) as failed."))
            return

        if options["mark_failed"] is not None:
            vid = options["mark_failed"]
            mark_failed_by_id(
                vid,
                "Processing timed out after 15 minutes.",
            )
            self.stdout.write(self.style.SUCCESS(f"Marked video {vid} as failed."))
            return

        if options["reprocess"] is not None:
            vid = options["reprocess"]
            try:
                video = TutorialVideo.objects.get(pk=vid)
            except TutorialVideo.DoesNotExist as exc:
                raise CommandError(f"Video {vid} not found") from exc
            if not (video.temp_s3_key or "").strip():
                raise CommandError(
                    f"Video {vid} has no temp_s3_key — re-upload required."
                )
            video.status = TutorialVideo.STATUS_PROCESSING
            video.processing_error = ""
            video.is_active = True
            video.save(
                update_fields=["status", "processing_error", "is_active", "updated_at"]
            )
            enqueue_tutorial_processing(vid)
            self.stdout.write(self.style.SUCCESS(f"Re-queued video {vid}."))
            return

        if options["reprocess_all_failed"]:
            qs = TutorialVideo.objects.filter(
                is_active=True,
                status=TutorialVideo.STATUS_FAILED,
            ).exclude(temp_s3_key="")
            count = 0
            for video in qs.iterator():
                video.status = TutorialVideo.STATUS_PROCESSING
                video.processing_error = ""
                video.save(
                    update_fields=["status", "processing_error", "updated_at"]
                )
                enqueue_tutorial_processing(video.pk)
                count += 1
            self.stdout.write(self.style.SUCCESS(f"Re-queued {count} failed video(s)."))
            return

        raise CommandError(
            "Specify --sweep, --reprocess <id>, --reprocess-all-failed, or --mark-failed <id>."
        )
