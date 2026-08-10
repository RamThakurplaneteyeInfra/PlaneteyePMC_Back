"""
Project Extension of Time (EOT) — multiple records per project.

Normalized Project → ProjectEOT (one-to-many).
Legacy ProjectDates.eot_date is kept in sync with the latest approved EOT
for backward-compatible clients.
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from projects.models import Project


class ProjectEOT(models.Model):
    """A single Extension of Time claim/approval for a project."""

    STATUS_PENDING = "pending"
    STATUS_SUBMITTED = "submitted"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
    ]

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="eots",
        db_index=True,
        help_text="Project this EOT belongs to",
    )
    project_dates = models.ForeignKey(
        "project_dates.ProjectDates",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="eot_records",
        help_text="Optional link to SCL/Contractor schedule row",
    )
    eot_number = models.PositiveIntegerField(
        help_text="Sequential EOT number within the project (1, 2, 3…)",
    )
    extension_days = models.PositiveIntegerField(
        help_text="Approved/requested extension in calendar days (must be > 0)",
    )
    original_completion_date = models.DateField(
        help_text="Completion date before this EOT",
    )
    revised_completion_date = models.DateField(
        help_text="Completion date after applying this EOT",
    )
    approval_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date the EOT was approved (required when status=approved)",
    )
    reason = models.TextField(help_text="Primary reason for the extension")
    remarks = models.TextField(blank=True, default="", help_text="Optional notes")
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )
    supporting_document_key = models.CharField(
        max_length=512,
        blank=True,
        default="",
        db_index=True,
        help_text="S3 object key under eot/… (empty if no document)",
    )
    supporting_document_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Original uploaded filename",
    )
    supporting_document_url = models.URLField(
        max_length=1024,
        blank=True,
        default="",
        help_text="Public HTTPS URL for the supporting document on S3",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_eots",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_eots",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="False = soft-deleted; excluded from latest completion calculations",
    )

    class Meta:
        ordering = ["project_id", "eot_number"]
        verbose_name = "Project EOT"
        verbose_name_plural = "Project EOTs"
        constraints = [
            models.UniqueConstraint(
                fields=["project", "eot_number"],
                condition=Q(is_active=True),
                name="eot_unique_active_number_per_project",
            ),
            models.CheckConstraint(
                condition=Q(extension_days__gt=0),
                name="eot_extension_days_positive",
            ),
        ]
        indexes = [
            models.Index(fields=["project", "status", "is_active"], name="eot_proj_status_active_idx"),
            models.Index(fields=["project", "-eot_number"], name="eot_proj_number_desc_idx"),
        ]

    def clean(self):
        errors = {}
        if self.extension_days is not None and self.extension_days <= 0:
            errors["extension_days"] = "extension_days must be greater than 0."

        if (
            self.original_completion_date
            and self.revised_completion_date
            and self.revised_completion_date < self.original_completion_date
        ):
            errors["revised_completion_date"] = (
                "revised_completion_date must be on or after original_completion_date."
            )

        if self.status == self.STATUS_APPROVED and not self.approval_date:
            errors["approval_date"] = "approval_date is required when status is approved."

        if self.is_active and self.project_id and self.eot_number:
            qs = ProjectEOT.objects.filter(
                project_id=self.project_id,
                eot_number=self.eot_number,
                is_active=True,
            )
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                errors["eot_number"] = (
                    f"EOT number {self.eot_number} already exists for this project."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        name = self.project.name if self.project_id else "Unknown"
        return f"{name} — EOT #{self.eot_number} [{self.status}] {self.extension_days}d"
