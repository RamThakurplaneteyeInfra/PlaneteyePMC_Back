from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Max
from django.utils import timezone

from projects.models import Project

from .correspondence import CorrespondenceDocument


def _file_stem(filename: str) -> str:
    stem = Path(filename or "document").stem
    return re.sub(r"_v\d+$", "", stem) or "document"


class CorrespondenceDocumentAttachment(models.Model):
    correspondence = models.ForeignKey(
        CorrespondenceDocument,
        on_delete=models.CASCADE,
        related_name="attachments",
        db_index=True,
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="correspondence_attachments",
        db_index=True,
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_correspondence_attachments",
    )
    file_name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    document_type = models.CharField(max_length=120, blank=True)
    document_version = models.PositiveIntegerField(default=1, db_index=True)
    version_group = models.CharField(max_length=255, db_index=True)
    original_file_size = models.PositiveBigIntegerField(default=0)
    compressed_file_size = models.PositiveBigIntegerField(default=0)
    compression_percentage = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=0,
    )
    content_type = models.CharField(max_length=120)
    s3_key = models.CharField(max_length=700, unique=True)
    s3_url = models.URLField(max_length=1000)
    uploaded_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_correspondence_attachments",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_correspondence_attachments",
    )

    class Meta:
        ordering = ["-uploaded_at", "-document_version"]
        indexes = [
            models.Index(
                fields=["correspondence", "is_active", "uploaded_at"],
                name="corr_att_corr_active_idx",
            ),
            models.Index(
                fields=["correspondence", "version_group", "document_version"],
                name="corr_att_version_idx",
            ),
        ]
        verbose_name = "Correspondence Document Attachment"
        verbose_name_plural = "Correspondence Document Attachments"

    def __str__(self) -> str:
        return (
            f"{self.file_name} v{self.document_version} "
            f"(correspondence #{self.correspondence_id})"
        )

    @classmethod
    def build_version_group(cls, correspondence_id: int, filename: str) -> str:
        return f"{correspondence_id}:{_file_stem(filename)}"

    @classmethod
    def next_version(cls, correspondence_id: int, filename: str) -> int:
        group = cls.build_version_group(correspondence_id, filename)
        current = cls.objects.filter(
            correspondence_id=correspondence_id,
            version_group=group,
        ).aggregate(max_version=Max("document_version"))["max_version"]
        return (current or 0) + 1

    def clean(self):
        errors = {}
        if self.document_version < 1:
            errors["document_version"] = "document_version must be >= 1."
        if not (self.file_name or "").strip():
            errors["file_name"] = "file_name is required."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.file_name:
            self.file_name = self.file_name.strip()
        if not self.version_group:
            self.version_group = self.build_version_group(
                self.correspondence_id,
                self.file_name,
            )
        self.full_clean()
        super().save(*args, **kwargs)
