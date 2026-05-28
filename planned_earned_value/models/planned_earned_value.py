"""
Planned vs Earned Value Model.

Tracks planned value (PV) against earned value (EV) per project.
Automatically computes:
  - variance            = earnedValue - plannedValue
  - variancePercentage  = (variance / plannedValue) * 100
  - performancePercentage = (earnedValue / plannedValue) * 100

Key design decisions:
  - earnedValue CAN exceed plannedValue (ahead of schedule / over-performing).
  - earnedValue CAN be less than plannedValue (behind schedule / under-performing).
  - Both values must be non-negative (no negative work done or planned).
  - Division-by-zero is handled: percentages default to 0.0 when plannedValue = 0.
  - All percentages are rounded to 2 decimal places for clean dashboard display.

Designed for PMC dashboard KPI cards, gauge meters, and performance charts.

Scalable for future additions:
  - monthly planned vs earned tracking
  - trend analysis and baseline comparison
  - schedule variance (SV) and cost variance (CV)
  - forecasting analytics (EAC, ETC, TCPI)
  - project health indicators (SPI, CPI)
  - S-curve chart data
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class PlannedEarnedValue(models.Model):
    """
    One cumulative record per project capturing Planned vs Earned Value KPIs.

    Calculated fields (variance, variancePercentage, performancePercentage)
    are stored in the DB so dashboard queries never need to compute them
    on the fly — critical for real-time gauge and chart rendering.
    """

    # -------------------------------------------------------------------------
    # Core input fields
    # -------------------------------------------------------------------------
    projectName = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="Unique project name for this Planned vs Earned Value record",
    )
    plannedValue = models.DecimalField(
        max_digits=20,
        decimal_places=4,
        default=0,
        help_text="Planned Value (PV) — budgeted cost of work scheduled",
    )
    earnedValue = models.DecimalField(
        max_digits=20,
        decimal_places=4,
        default=0,
        help_text=(
            "Earned Value (EV) — budgeted cost of work performed. "
            "Can be greater than plannedValue (ahead of schedule)."
        ),
    )

    # -------------------------------------------------------------------------
    # Auto-calculated fields (read-only; set in save())
    # -------------------------------------------------------------------------
    variance = models.DecimalField(
        max_digits=20,
        decimal_places=4,
        default=0,
        editable=False,
        help_text=(
            "Auto-calculated: earnedValue - plannedValue. "
            "Positive = ahead of schedule. Negative = behind schedule."
        ),
    )
    variancePercentage = models.FloatField(
        default=0.0,
        editable=False,
        help_text=(
            "Auto-calculated: (variance / plannedValue) * 100. "
            "0.0 when plannedValue = 0."
        ),
    )
    performancePercentage = models.FloatField(
        default=0.0,
        editable=False,
        help_text=(
            "Auto-calculated: (earnedValue / plannedValue) * 100. "
            "Represents Schedule Performance Index as a percentage. "
            "0.0 when plannedValue = 0."
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
        Field-level validation.
        - plannedValue must be >= 0.
        - earnedValue must be >= 0.
        (earnedValue > plannedValue is intentionally allowed.)
        """
        errors = {}

        if self.plannedValue is not None and self.plannedValue < 0:
            errors["plannedValue"] = (
                "plannedValue must be >= 0. "
                f"Got {self.plannedValue}."
            )

        if self.earnedValue is not None and self.earnedValue < 0:
            errors["earnedValue"] = (
                "earnedValue must be >= 0. "
                f"Got {self.earnedValue}."
            )

        if errors:
            raise ValidationError(errors)

    # =========================================================================
    # Auto-calculation on save
    # =========================================================================

    def save(self, *args, **kwargs):
        """
        Override save to:
        1. Normalize projectName (strip whitespace).
        2. Auto-calculate variance, variancePercentage, performancePercentage.
        3. Run full_clean() to enforce field validation before persisting.

        Calculation rules:
          variance             = earnedValue - plannedValue
          variancePercentage   = (variance / plannedValue) * 100
          performancePercentage = (earnedValue / plannedValue) * 100

        Division-by-zero guard:
          When plannedValue = 0, both percentage fields default to 0.0.
        """
        # 1. Normalize project name
        if self.projectName:
            self.projectName = self.projectName.strip()

        pv = self.plannedValue or 0
        ev = self.earnedValue or 0

        # 2. Auto-calculate variance (can be negative — behind schedule)
        self.variance = ev - pv

        # 3. Auto-calculate percentages (guard against division by zero)
        if pv > 0:
            self.variancePercentage = round(
                float(self.variance / pv) * 100, 2
            )
            self.performancePercentage = round(
                float(ev / pv) * 100, 2
            )
        else:
            # plannedValue = 0: percentages are undefined; default to 0.0
            self.variancePercentage = 0.0
            self.performancePercentage = 0.0

        # 4. Validate before persisting
        self.full_clean()

        super().save(*args, **kwargs)

    # =========================================================================
    # Computed properties (Python-only, not stored — for convenience)
    # =========================================================================

    @property
    def schedulePerformanceIndex(self) -> float:
        """
        SPI = earnedValue / plannedValue.
        SPI > 1.0 → ahead of schedule.
        SPI < 1.0 → behind schedule.
        Returns 0.0 when plannedValue = 0.
        """
        if not self.plannedValue or self.plannedValue == 0:
            return 0.0
        return round(float(self.earnedValue / self.plannedValue), 4)

    @property
    def performanceStatus(self) -> str:
        """
        Human-readable performance status for dashboard badges.
        Based on performancePercentage:
          >= 100  → 'ahead'
          >= 90   → 'on_track'
          >= 75   → 'at_risk'
          < 75    → 'behind'
        """
        pct = self.performancePercentage
        if pct >= 100:
            return "ahead"
        elif pct >= 90:
            return "on_track"
        elif pct >= 75:
            return "at_risk"
        else:
            return "behind"

    # =========================================================================
    # Meta & helpers
    # =========================================================================

    def __str__(self) -> str:
        return (
            f"{self.projectName} — "
            f"PV={self.plannedValue} / EV={self.earnedValue} "
            f"({self.performancePercentage}%)"
        )

    class Meta:
        ordering = ["projectName"]
        verbose_name = "Planned vs Earned Value"
        verbose_name_plural = "Planned vs Earned Value Records"
        indexes = [
            models.Index(
                fields=["projectName"],
                name="pev_project_name_idx",
            ),
        ]
