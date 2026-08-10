"""
Tutorial / training videos — global (not project-scoped), section-tagged.

Upload accepts only title, description, section, upload.
Compression runs asynchronously; playback streams from S3/CloudFront.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from tutorial_videos.sections import TUTORIAL_SECTION_CHOICES


class TutorialVideo(models.Model):
    STATUS_PROCESSING = "processing"
    STATUS_READY = "ready"
    STATUS_FAILED = "failed"
    STATUS_DELETED = "deleted"
    STATUS_CHOICES = [
        (STATUS_PROCESSING, "Processing"),
        (STATUS_READY, "Ready"),
        (STATUS_FAILED, "Failed"),
        (STATUS_DELETED, "Deleted"),
    ]

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    section = models.CharField(
        max_length=64,
        choices=TUTORIAL_SECTION_CHOICES,
        db_index=True,
        help_text="Stable sidebar section key (e.g. meeting_documents)",
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PROCESSING,
        db_index=True,
    )
    processing_error = models.CharField(max_length=500, blank=True, default="")

    # Temporary (original) object — cleared after successful processing.
    temp_s3_key = models.CharField(max_length=512, blank=True, default="")
    original_filename = models.CharField(max_length=255, blank=True, default="")
    original_file_size = models.BigIntegerField(null=True, blank=True)
    original_content_type = models.CharField(max_length=100, blank=True, default="")

    # Optimized playback object
    optimized_s3_key = models.CharField(max_length=512, blank=True, default="", db_index=True)
    video_url = models.URLField(max_length=1024, blank=True, default="")
    file_size = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="Optimized file size in bytes",
    )
    duration_seconds = models.FloatField(null=True, blank=True)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    compression_ratio = models.FloatField(
        null=True,
        blank=True,
        help_text="original_size / optimized_size when both known",
    )
    processing_ms = models.PositiveIntegerField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_tutorial_videos",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Tutorial Video"
        verbose_name_plural = "Tutorial Videos"
        indexes = [
            models.Index(
                fields=["is_active", "status", "-created_at"],
                name="tutorial_active_status_idx",
            ),
            # Primary frontend query: ?section=…&is_active + order by -created_at
            models.Index(
                fields=["section", "is_active", "-created_at"],
                name="tutorial_section_active_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.title} [{self.section}/{self.status}]"
