"""
Monthly Construction Progress Model.

Tracks monthly construction progress KPIs per project.
Automatically computes:
  - variance              = actualProgress - plannedProgress
  - performancePercentage = (actualProgress / plannedProgress) * 100

Key design decisions:
  - One record per project per month (unique_together on projectName + progressMonth).
  - progressMonth must be in YYYY-MM format (e.g. "2026-05").
  - plannedProgress and actualProgress are percentages (0–100).
  - Division-by-zero is handled: performancePercentage defaults to 0.0
    when plannedProgress = 0.
  - Percentages are rounded to 2 decimal places.
  - remarks is optional free-text for delay notes, site conditions, etc.

Designed for:
  - PMC dashboard planned vs actual progress charts
  - Monthly S-curve analytics
  - KPI cards and trend analysis
  - Delay tracking and project forecasting

Scalable for future additions:
  - Cumulative progress tracking
  - Milestone-based progress
  - Yearly rollup reports
  - Category-wise progress (civil, MEP, finishing …)
  - Forecast-to-complete calculations
"""

import re

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

# YYYY-MM format validator
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _validate_progress_month(value: str):
    """Reject any progressMonth that is not in YYYY-MM format."""
    if not _MONTH_RE.match(value):
        raise ValidationError(
            "progressMonth must be in YYYY-MM format (e.g. '2026-05')."
        )


class ConstructionProgress(models.Model):
    """
    One record per project per month capturing construction progress KPIs.

    Calculated fields (variance, performancePercentage) are stored in the DB
    so dashboard queries never need to compute them on the fly.
    """

    # -------------------------------------------------------------------------
    # Core identifiers
    # -------------------------------------------------------------------------
    projectName = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Project name this progress record belongs to",
    )
    progressMonth = models.CharField(
        max_length=7,
        db_index=True,
        validators=[_validate_progress_month],
        help_text="Month of progress in YYYY-MM format (e.g. '2026-05')",
    )

    # -------------------------------------------------------------------------
    # Input fields
    # -------------------------------------------------------------------------
    plannedProgress = models.FloatField(
        default=0.0,
        help_text="Planned progress percentage for this month (0–100)",
    )
    actualProgress = models.FloatField(
        default=0.0,
        help_text="Actual progress percentage achieved this month (0–100)",
    )
    remarks = models.TextField(
        blank=True,
        default="",
        help_text="Optional remarks — delay reasons, site conditions, etc.",
    )

    # -------------------------------------------------------------------------
    # Auto-calculated fields (read-only; set in save())
    # -------------------------------------------------------------------------
    variance = models.FloatField(
        default=0.0,
        editable=False,
        help_text=(
            "Auto-calculated: actualProgress - plannedProgress. "
            "Negative = behind schedule, positive = ahead of schedule."
        ),
    )
    performancePercentage = models.FloatField(
        default=0.0,
        editable=False,
        help_text=(
            "Auto-calculated: (actualProgress / plannedProgress) * 100. "
            "0.0 when plannedProgress = 0."
        ),
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
        """
        Field-level and cross-field validation.
        - plannedProgress and actualProgress must be >= 0.
        - Neither value should exceed 100 (percentage cap).
        """
        errors = {}

        planned = self.plannedProgress if self.plannedProgress is not None else 0.0
        actual = self.actualProgress if self.actualProgress is not None else 0.0

        if planned < 0:
            errors["plannedProgress"] = "plannedProgress must be >= 0."
        if actual < 0:
            errors["actualProgress"] = "actualProgress must be >= 0."
        if planned > 100:
            errors["plannedProgress"] = "plannedProgress cannot exceed 100%."
        if actual > 100:
            errors["actualProgress"] = "actualProgress cannot exceed 100%."

        if errors:
            raise ValidationError(errors)

    # =========================================================================
    # Auto-calculation on save
    # =========================================================================

    def save(self, *args, **kwargs):
        """
        Override save to:
        1. Normalize projectName and progressMonth.
        2. Auto-calculate variance and performancePercentage.
        """
        # 1. Normalize
        if self.projectName:
            self.projectName = self.projectName.strip()
        if self.progressMonth:
            self.progressMonth = self.progressMonth.strip()

        planned = self.plannedProgress or 0.0
        actual = self.actualProgress or 0.0

        # 2. variance: negative = behind schedule, positive = ahead
        self.variance = round(actual - planned, 2)

        # 3. performance percentage (guard division by zero)
        if planned > 0:
            self.performancePercentage = round((actual / planned) * 100, 2)
        else:
            self.performancePercentage = 0.0

        super().save(*args, **kwargs)

    # =========================================================================
    # Computed properties (Python-only, not stored)
    # =========================================================================

    @property
    def progressStatus(self) -> str:
        """
        Human-readable schedule status for dashboard badges.
        Based on performancePercentage:
          >= 100 → 'on_track'
          >= 80  → 'slight_delay'
          >= 60  → 'delayed'
          < 60   → 'critical'
        """
        pct = self.performancePercentage
        if pct >= 100:
            return "on_track"
        elif pct >= 80:
            return "slight_delay"
        elif pct >= 60:
            return "delayed"
        else:
            return "critical"

    # =========================================================================
    # Meta & helpers
    # =========================================================================

    def __str__(self) -> str:
        return (
            f"{self.projectName} [{self.progressMonth}] — "
            f"Planned: {self.plannedProgress}%, Actual: {self.actualProgress}% "
            f"(Variance: {self.variance:+.2f}%)"
        )

    class Meta:
        ordering = ["projectName", "progressMonth"]
        verbose_name = "Monthly Construction Progress"
        verbose_name_plural = "Monthly Construction Progress Records"
        # One record per project per month — unique btree covers (projectName, progressMonth)
        unique_together = [("projectName", "progressMonth")]
        indexes = [
            # Month-only scans / cross-project month dashboards
            models.Index(
                fields=["progressMonth"],
                name="conprog_month_idx",
            ),
        ]
