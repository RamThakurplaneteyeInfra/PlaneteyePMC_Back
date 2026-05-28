"""
Monthly Project Equipment Tracking Model.

Tracks monthly equipment deployment KPIs per project.
Automatically computes:
  - variance              = actualEquipment - plannedEquipment
  - performancePercentage = (actualEquipment / plannedEquipment) * 100

Key design decisions:
  - One record per project per month (unique_together on projectName + equipmentMonth).
  - equipmentMonth must be in YYYY-MM format (e.g. "2026-05").
  - plannedEquipment and actualEquipment are non-negative integer counts.
  - Division-by-zero is handled: performancePercentage defaults to 0.0
    when plannedEquipment = 0.
  - Percentages are rounded to 2 decimal places.
  - remarks is optional free-text for shortage notes, maintenance issues, etc.

Designed for:
  - PMC dashboard planned vs actual equipment bar charts
  - Monthly equipment trend monitoring
  - KPI cards and variance analytics
  - Resource forecasting and utilization tracking

Scalable for future additions:
  - Equipment category breakdown (heavy, light, specialised)
  - Machinery-level tracking
  - Equipment utilization and downtime analytics
  - Maintenance status integration
  - Project resource forecasting
"""

import re

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _validate_equipment_month(value: str):
    """Reject any equipmentMonth that is not in YYYY-MM format."""
    if not _MONTH_RE.match(value):
        raise ValidationError(
            "equipmentMonth must be in YYYY-MM format (e.g. '2026-05')."
        )


class ProjectEquipment(models.Model):
    """
    One record per project per month capturing equipment deployment KPIs.

    Calculated fields (variance, performancePercentage) are stored in the DB
    so dashboard queries never need to compute them on the fly.
    """

    # -------------------------------------------------------------------------
    # Core identifiers
    # -------------------------------------------------------------------------
    projectName = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Project name this equipment record belongs to",
    )
    equipmentMonth = models.CharField(
        max_length=7,
        db_index=True,
        validators=[_validate_equipment_month],
        help_text="Month of equipment tracking in YYYY-MM format (e.g. '2026-05')",
    )

    # -------------------------------------------------------------------------
    # Input fields
    # -------------------------------------------------------------------------
    plannedEquipment = models.PositiveIntegerField(
        default=0,
        help_text="Planned equipment count for this month",
    )
    actualEquipment = models.PositiveIntegerField(
        default=0,
        help_text="Actual equipment deployed this month",
    )
    remarks = models.TextField(
        blank=True,
        default="",
        help_text="Optional remarks — shortage reasons, maintenance issues, etc.",
    )

    # -------------------------------------------------------------------------
    # Auto-calculated fields (read-only; set in save())
    # -------------------------------------------------------------------------
    variance = models.IntegerField(
        default=0,
        editable=False,
        help_text=(
            "Auto-calculated: actualEquipment - plannedEquipment. "
            "Negative = shortfall, positive = surplus."
        ),
    )
    performancePercentage = models.FloatField(
        default=0.0,
        editable=False,
        help_text=(
            "Auto-calculated: (actualEquipment / plannedEquipment) * 100. "
            "0.0 when plannedEquipment = 0."
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
    # Auto-calculation on save
    # =========================================================================

    def save(self, *args, **kwargs):
        """
        Override save to:
        1. Normalize projectName and equipmentMonth.
        2. Auto-calculate variance and performancePercentage.
        """
        if self.projectName:
            self.projectName = self.projectName.strip()
        if self.equipmentMonth:
            self.equipmentMonth = self.equipmentMonth.strip()

        planned = self.plannedEquipment or 0
        actual = self.actualEquipment or 0

        # variance: negative = shortfall, positive = surplus
        self.variance = actual - planned

        # performance percentage (guard division by zero)
        if planned > 0:
            self.performancePercentage = round((actual / planned) * 100, 2)
        else:
            self.performancePercentage = 0.0

        super().save(*args, **kwargs)

    # =========================================================================
    # Computed properties (Python-only, not stored)
    # =========================================================================

    @property
    def equipmentStatus(self) -> str:
        """
        Human-readable deployment status for dashboard badges.
        Based on performancePercentage:
          >= 100 → 'fully_deployed'
          >= 80  → 'near_target'
          >= 60  → 'shortfall'
          < 60   → 'critical_shortfall'
        """
        pct = self.performancePercentage
        if pct >= 100:
            return "fully_deployed"
        elif pct >= 80:
            return "near_target"
        elif pct >= 60:
            return "shortfall"
        else:
            return "critical_shortfall"

    # =========================================================================
    # Meta & helpers
    # =========================================================================

    def __str__(self) -> str:
        return (
            f"{self.projectName} [{self.equipmentMonth}] — "
            f"Planned: {self.plannedEquipment}, Actual: {self.actualEquipment} "
            f"(Variance: {self.variance:+d})"
        )

    class Meta:
        ordering = ["projectName", "equipmentMonth"]
        verbose_name = "Monthly Project Equipment"
        verbose_name_plural = "Monthly Project Equipment Records"
        unique_together = [("projectName", "equipmentMonth")]
        indexes = [
            models.Index(fields=["projectName"], name="pe_project_name_idx"),
            models.Index(fields=["equipmentMonth"], name="pe_equipment_month_idx"),
            models.Index(fields=["projectName", "equipmentMonth"], name="pe_project_month_idx"),
        ]
