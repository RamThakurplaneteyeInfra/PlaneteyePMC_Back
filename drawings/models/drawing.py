"""
Drawing Summary Model.

Monthly drawing submission/approval tracking per project.
variance and approval_rate are computed in the serializer — never stored.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from projects.models import Project


class DrawingSummary(models.Model):
    """
    One monthly drawing summary per (project, month, year).
    """

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="drawing_summaries",
        db_index=True,
        help_text="Project this drawing summary belongs to",
    )
    month = models.PositiveSmallIntegerField(
        db_index=True,
        help_text="Month number (1–12)",
    )
    year = models.PositiveSmallIntegerField(
        db_index=True,
        help_text="Year (e.g. 2026)",
    )

    submitted_drawings = models.PositiveIntegerField(
        default=0,
        help_text="Drawings submitted this month",
    )
    approved_drawings = models.PositiveIntegerField(
        default=0,
        help_text="Drawings approved this month (cannot exceed submitted_drawings)",
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

        for field in ("submitted_drawings", "approved_drawings"):
            value = getattr(self, field)
            if value is not None and value < 0:
                errors[field] = f"{field} must be >= 0."

        submitted = self.submitted_drawings or 0
        approved = self.approved_drawings or 0

        if approved > submitted:
            errors["approved_drawings"] = (
                f"approved_drawings ({approved}) cannot be greater than "
                f"submitted_drawings ({submitted})."
            )

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
            f"{self.project_name} ({self.month:02d}/{self.year}) — "
            f"{self.approved_drawings}/{self.submitted_drawings} approved"
        )

    class Meta:
        ordering = ["project__name", "year", "month"]
        verbose_name = "Drawing Summary"
        verbose_name_plural = "Drawing Summaries"
        unique_together = [("project", "month", "year")]
        indexes = [
            models.Index(
                fields=["project", "year", "month"],
                name="drawing_proj_year_month_idx",
            ),
            models.Index(fields=["year", "month"], name="drawing_year_month_idx"),
        ]


# Backward-compatible alias
Drawing = DrawingSummary
