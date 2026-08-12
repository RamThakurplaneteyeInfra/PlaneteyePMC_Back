"""Drawing file attachments stored in S3 (multiple per register item / revision)."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from .drawing_register import DrawingRegisterItem


class DrawingFile(models.Model):
    drawing_register = models.ForeignKey(
        DrawingRegisterItem,
        on_delete=models.CASCADE,
        related_name="files",
        db_index=True,
    )
    revision = models.PositiveSmallIntegerField(
        help_text="Drawing revision at upload time (immutable snapshot)",
    )
    original_filename = models.CharField(max_length=255)
    s3_key = models.CharField(max_length=512, unique=True)
    file_url = models.URLField(max_length=1024)
    file_size = models.PositiveBigIntegerField(default=0)
    content_type = models.CharField(max_length=128, blank=True, default="")
    file_extension = models.CharField(max_length=16, blank=True, default="")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_drawing_files",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "id"]
        verbose_name = "Drawing File"
        verbose_name_plural = "Drawing Files"
        indexes = [
            models.Index(
                fields=["drawing_register", "revision", "is_active"],
                name="draw_file_reg_rev_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.original_filename} (rev {self.revision})"
