"""
Project Quality Status Model.

Monthly quality testing KPIs per project.
Calculated metrics (shortfall, quality_performance, pass_rate, fail_rate)
are computed in the serializer — never stored in the database.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class ProjectQualityStatus(models.Model):
    """
    One monthly quality record per (projectName, month, year).
    """

    # -------------------------------------------------------------------------
    # Core identifiers
    # -------------------------------------------------------------------------
    projectName = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Project name for this quality status record",
    )
    month = models.PositiveSmallIntegerField(
        db_index=True,
        help_text="Month number (1–12)",
    )
    year = models.PositiveSmallIntegerField(
        db_index=True,
        help_text="Year (e.g. 2026)",
    )

    # -------------------------------------------------------------------------
    # Input fields
    # -------------------------------------------------------------------------
    tests_required = models.PositiveIntegerField(
        default=0,
        help_text="Number of quality tests required for the month",
    )
    tests_conducted = models.PositiveIntegerField(
        default=0,
        help_text="Number of quality tests conducted",
    )
    tests_passed = models.PositiveIntegerField(
        default=0,
        help_text="Number of tests passed",
    )
    tests_failed = models.PositiveIntegerField(
        default=0,
        help_text="Number of tests failed",
    )

    # -------------------------------------------------------------------------
    # Timestamps
    # -------------------------------------------------------------------------
    created_at = models.DateTimeField(
        default=timezone.now,
        editable=False,
        db_index=True,
        help_text="Record creation timestamp",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Last update timestamp",
    )

    # =========================================================================
    # Validation
    # =========================================================================

    def clean(self):
        errors = {}

        if self.month is not None and not (1 <= self.month <= 12):
            errors["month"] = "month must be between 1 and 12."

        if self.year is not None and not (2000 <= self.year <= 2100):
            errors["year"] = "year must be between 2000 and 2100."

        for field in (
            "tests_required",
            "tests_conducted",
            "tests_passed",
            "tests_failed",
        ):
            value = getattr(self, field)
            if value is not None and value < 0:
                errors[field] = f"{field} must be >= 0."

        conducted = self.tests_conducted or 0
        passed = self.tests_passed or 0
        failed = self.tests_failed or 0

        if passed + failed > conducted:
            errors["tests_passed"] = (
                f"tests_passed ({passed}) + tests_failed ({failed}) cannot exceed "
                f"tests_conducted ({conducted})."
            )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.projectName:
            self.projectName = self.projectName.strip()
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return (
            f"{self.projectName} ({self.month:02d}/{self.year}) — "
            f"{self.tests_passed}/{self.tests_conducted} passed"
        )

    class Meta:
        ordering = ["projectName", "year", "month"]
        verbose_name = "Project Quality Status"
        verbose_name_plural = "Project Quality Status Records"
        unique_together = [("projectName", "month", "year")]
        indexes = [
            models.Index(
                fields=["projectName", "year", "month"],
                name="pqs_proj_year_month_idx",
            ),
            models.Index(fields=["year", "month"], name="pqs_year_month_idx"),
        ]
