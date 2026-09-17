"""
Testing Documents — project testing reports (PDF / image / video) in private S3.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from projects.models import Project


class TestingDocument(models.Model):
    DOCUMENT_TYPE_PDF = "pdf"
    DOCUMENT_TYPE_IMAGE = "image"
    DOCUMENT_TYPE_VIDEO = "video"
    DOCUMENT_TYPE_CHOICES = [
        (DOCUMENT_TYPE_PDF, "PDF"),
        (DOCUMENT_TYPE_IMAGE, "Image"),
        (DOCUMENT_TYPE_VIDEO, "Video"),
    ]

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="testing_documents",
        db_index=True,
    )
    title = models.CharField(max_length=255, db_index=True)
    remarks = models.TextField(blank=True)

    # S3 object key stored as `file` per API contract
    file = models.CharField(
        max_length=700,
        unique=True,
        help_text="S3 object key under testing/",
    )
    file_url = models.URLField(max_length=1000)
    file_name = models.CharField(max_length=255)
    file_size = models.PositiveBigIntegerField(default=0)
    mime_type = models.CharField(max_length=120)
    document_type = models.CharField(
        max_length=16,
        choices=DOCUMENT_TYPE_CHOICES,
        db_index=True,
    )

    test_date = models.DateField(db_index=True)
    month = models.PositiveSmallIntegerField(db_index=True)
    year = models.PositiveSmallIntegerField(db_index=True)

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_testing_documents",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["-test_date", "-created_at"]
        verbose_name = "Testing Document"
        verbose_name_plural = "Testing Documents"
        indexes = [
            models.Index(
                fields=["project", "year", "month"],
                name="test_doc_proj_year_month_idx",
            ),
            models.Index(
                fields=["project", "document_type", "is_active"],
                name="test_doc_proj_type_active_idx",
            ),
            models.Index(
                fields=["uploaded_by", "created_at"],
                name="test_doc_uploader_created_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.project_id})"

    def clean(self):
        errors = {}
        if self.test_date:
            if self.month and self.month != self.test_date.month:
                errors["month"] = "month must match test_date."
            if self.year and self.year != self.test_date.year:
                errors["year"] = "year must match test_date."
        if self.month is not None and not (1 <= self.month <= 12):
            errors["month"] = "month must be between 1 and 12."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.test_date:
            self.month = self.test_date.month
            self.year = self.test_date.year
        if self.title:
            self.title = self.title.strip()
        super().save(*args, **kwargs)


class TestingDocumentAuditLog(models.Model):
    ACTION_CREATED = "created"
    ACTION_UPDATED = "updated"
    ACTION_DELETED = "deleted"
    ACTION_CHOICES = [
        (ACTION_CREATED, "Created"),
        (ACTION_UPDATED, "Updated"),
        (ACTION_DELETED, "Deleted"),
    ]

    document = models.ForeignKey(
        TestingDocument,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    document_id_snapshot = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Preserved document id after soft/hard delete",
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="testing_document_audit_logs",
    )
    action = models.CharField(max_length=16, choices=ACTION_CHOICES, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="testing_document_audit_actions",
    )
    detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Testing Document Audit Log"
        verbose_name_plural = "Testing Document Audit Logs"

    def __str__(self) -> str:
        return f"{self.action} doc={self.document_id_snapshot} @ {self.created_at}"
