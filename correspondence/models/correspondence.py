"""
Correspondence & Delivery Status Model.

Monthly correspondence tracking per project and type (CLIENT / CONTRACTOR).
pending_correspondence and delivery_efficiency are computed in the serializer — never stored.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from projects.models import Project


class CorrespondenceStatus(models.Model):
    """
    One monthly correspondence record per (project, month, year, correspondence_type).
    """

    TYPE_CLIENT = "CLIENT"
    TYPE_CONTRACTOR = "CONTRACTOR"

    CORRESPONDENCE_TYPE_CHOICES = [
        (TYPE_CLIENT, "CLIENT"),
        (TYPE_CONTRACTOR, "CONTRACTOR"),
    ]

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="correspondence_records",
        db_index=True,
        help_text="Project this correspondence record belongs to",
    )
    month = models.PositiveSmallIntegerField(
        db_index=True,
        help_text="Month number (1–12)",
    )
    year = models.PositiveSmallIntegerField(
        db_index=True,
        help_text="Year (e.g. 2026)",
    )
    correspondence_type = models.CharField(
        max_length=20,
        choices=CORRESPONDENCE_TYPE_CHOICES,
        db_index=True,
        help_text="CLIENT or CONTRACTOR",
    )

    correspondence_received = models.PositiveIntegerField(
        default=0,
        help_text="Correspondence items received this month",
    )
    correspondence_delivered = models.PositiveIntegerField(
        default=0,
        help_text="Correspondence items delivered this month",
    )

    created_at = models.DateTimeField(
        default=timezone.now,
        editable=False,
        db_index=True,
    )
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        errors = {}

        if self.month is not None and not (1 <= self.month <= 12):
            errors["month"] = "month must be between 1 and 12."

        if self.year is not None and not (2000 <= self.year <= 2100):
            errors["year"] = "year must be between 2000 and 2100."

        if self.correspondence_type and self.correspondence_type not in {
            self.TYPE_CLIENT,
            self.TYPE_CONTRACTOR,
        }:
            errors["correspondence_type"] = "correspondence_type must be CLIENT or CONTRACTOR."

        for field in ("correspondence_received", "correspondence_delivered"):
            value = getattr(self, field)
            if value is not None and value < 0:
                errors[field] = f"{field} must be >= 0."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def project_name(self) -> str:
        return self.project.name if self.project_id else ""

    def __str__(self) -> str:
        return (
            f"{self.project_name} [{self.correspondence_type}] "
            f"({self.month:02d}/{self.year}) — "
            f"{self.correspondence_delivered}/{self.correspondence_received} delivered"
        )

    class Meta:
        ordering = ["project__name", "year", "month", "correspondence_type"]
        verbose_name = "Correspondence Status"
        verbose_name_plural = "Correspondence Status Records"
        unique_together = [("project", "month", "year", "correspondence_type")]
        indexes = [
            models.Index(
                fields=["project", "year", "month", "correspondence_type"],
                name="corr_proj_period_type_idx",
            ),
            models.Index(fields=["year", "month"], name="corr_year_month_idx"),
        ]


# Backward-compatible alias
Correspondence = CorrespondenceStatus
