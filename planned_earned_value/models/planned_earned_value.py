"""
Planned vs Earned Value Model.

Tracks planned value (PV) against earned value (EV) per project, per value type
(SCL / CONTRACTOR), per month/year.

Automatically computes on save:
  - variance              = earnedValue - plannedValue
  - variancePercentage    = (variance / plannedValue) * 100
  - performancePercentage = (earnedValue / plannedValue) * 100

One record per (projectName, value_type, month, year).
Yearly totals for summary endpoints are aggregated dynamically via DB SUM.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class PlannedEarnedValue(models.Model):
    """
    Monthly Planned vs Earned Value record per project and value type (SCL / CONTRACTOR).
    """

    VALUE_TYPE_SCL = "SCL"
    VALUE_TYPE_CONTRACTOR = "CONTRACTOR"

    VALUE_TYPE_CHOICES = [
        (VALUE_TYPE_SCL, "SCL"),
        (VALUE_TYPE_CONTRACTOR, "CONTRACTOR"),
    ]

    # -------------------------------------------------------------------------
    # Core input fields
    # -------------------------------------------------------------------------
    projectName = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Project name for this Planned vs Earned Value record",
    )
    value_type = models.CharField(
        max_length=20,
        choices=VALUE_TYPE_CHOICES,
        default=VALUE_TYPE_SCL,
        db_index=True,
        help_text="SCL or CONTRACTOR",
    )
    month = models.PositiveSmallIntegerField(
        db_index=True,
        help_text="Month number (1–12)",
    )
    year = models.PositiveSmallIntegerField(
        db_index=True,
        help_text="Year (e.g. 2026)",
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
    # Auto-calculated fields (set in save(); exposed via serializer)
    # -------------------------------------------------------------------------
    variance = models.DecimalField(
        max_digits=20,
        decimal_places=4,
        default=0,
        editable=False,
        help_text="Auto-calculated: earnedValue - plannedValue",
    )
    variancePercentage = models.FloatField(
        default=0.0,
        editable=False,
        help_text="Auto-calculated: (variance / plannedValue) * 100",
    )
    performancePercentage = models.FloatField(
        default=0.0,
        editable=False,
        help_text="Auto-calculated: (earnedValue / plannedValue) * 100",
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

        if self.plannedValue is not None and self.plannedValue < 0:
            errors["plannedValue"] = (
                f"plannedValue must be >= 0. Got {self.plannedValue}."
            )

        if self.earnedValue is not None and self.earnedValue < 0:
            errors["earnedValue"] = (
                f"earnedValue must be >= 0. Got {self.earnedValue}."
            )

        if self.month is not None and not (1 <= self.month <= 12):
            errors["month"] = "month must be between 1 and 12."

        if self.year is not None and not (2000 <= self.year <= 2100):
            errors["year"] = "year must be between 2000 and 2100."

        if self.value_type and self.value_type not in {
            self.VALUE_TYPE_SCL,
            self.VALUE_TYPE_CONTRACTOR,
        }:
            errors["value_type"] = "value_type must be SCL or CONTRACTOR."

        if errors:
            raise ValidationError(errors)

    # =========================================================================
    # Auto-calculation on save
    # =========================================================================

    def save(self, *args, **kwargs):
        if self.projectName:
            self.projectName = self.projectName.strip()

        pv = self.plannedValue or 0
        ev = self.earnedValue or 0

        self.variance = ev - pv

        if pv > 0:
            self.variancePercentage = round(float(self.variance / pv) * 100, 2)
            self.performancePercentage = round(float(ev / pv) * 100, 2)
        else:
            self.variancePercentage = 0.0
            self.performancePercentage = 0.0

        self.full_clean()
        super().save(*args, **kwargs)

    # =========================================================================
    # Computed properties
    # =========================================================================

    @property
    def schedulePerformanceIndex(self) -> float:
        """SPI = earnedValue / plannedValue. Returns 0.0 when plannedValue = 0."""
        if not self.plannedValue or self.plannedValue == 0:
            return 0.0
        return round(float(self.earnedValue / self.plannedValue), 4)

    @property
    def spi(self) -> float:
        """Alias for schedulePerformanceIndex."""
        return self.schedulePerformanceIndex

    @property
    def performanceStatus(self) -> str:
        pct = self.performancePercentage
        if pct >= 100:
            return "ahead"
        elif pct >= 90:
            return "on_track"
        elif pct >= 75:
            return "at_risk"
        return "behind"

    def __str__(self) -> str:
        return (
            f"{self.projectName} [{self.value_type}] {self.month:02d}/{self.year} — "
            f"PV={self.plannedValue} / EV={self.earnedValue} "
            f"({self.performancePercentage}%)"
        )

    class Meta:
        ordering = ["projectName", "year", "month", "value_type"]
        verbose_name = "Planned vs Earned Value"
        verbose_name_plural = "Planned vs Earned Value Records"
        unique_together = [("projectName", "value_type", "month", "year")]
        indexes = [
            models.Index(
                fields=["projectName", "value_type", "year", "month"],
                name="pev_proj_type_year_month_idx",
            ),
            models.Index(fields=["year", "month"], name="pev_year_month_idx"),
        ]
