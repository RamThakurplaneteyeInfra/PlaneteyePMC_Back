"""
Contract Performance Model.

Tracks billing vs receipt performance per project.
Automatically computes:
  - variance              = billedValue - actualReceiptValue
  - variancePercentage    = (variance / billedValue) * 100
  - performancePercentage = (actualReceiptValue / billedValue) * 100

Key design decisions:
  - actualReceiptValue CAN exceed billedValue (over-collection edge case).
  - Both values must be non-negative.
  - Division-by-zero is handled: percentages default to 0.00 when billedValue = 0.
  - All percentages are rounded to 2 decimal places for clean dashboard display.
  - One record per project (unique on projectName).

Designed for PMC dashboard KPI cards, performance gauges,
financial analytics, and variance tracking.

Scalable for future additions:
  - Monthly contract performance tracking
  - Collection efficiency analytics
  - Payment trends and recovery forecasting
  - Project financial health indicators
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class ContractPerformance(models.Model):
    """
    One cumulative record per project capturing billing vs receipt KPIs.

    Calculated fields (variance, variancePercentage, performancePercentage)
    are stored in the DB so dashboard queries never need to compute them
    on the fly — critical for real-time gauge and chart rendering.
    """

    # -------------------------------------------------------------------------
    # Core identifier
    # -------------------------------------------------------------------------
    projectName = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="Unique project name for this contract performance record",
    )

    # -------------------------------------------------------------------------
    # Input financial fields
    # -------------------------------------------------------------------------
    billedValue = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Total billed value (>= 0)",
    )
    actualReceiptValue = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Actual receipt / collection value (>= 0)",
    )
    cosExtraItem = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="COS / Extra Item value (>= 0). Manually editable; not used in KPI auto-calcs.",
    )

    # -------------------------------------------------------------------------
    # Auto-calculated fields (read-only; set in save())
    # -------------------------------------------------------------------------
    variance = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal("0.00"),
        editable=False,
        help_text=(
            "Auto-calculated: billedValue - actualReceiptValue. "
            "Positive = under-collected. Negative = over-collected."
        ),
    )
    variancePercentage = models.FloatField(
        default=0.0,
        editable=False,
        help_text=(
            "Auto-calculated: (variance / billedValue) * 100. "
            "0.0 when billedValue = 0."
        ),
    )
    performancePercentage = models.FloatField(
        default=0.0,
        editable=False,
        help_text=(
            "Auto-calculated: (actualReceiptValue / billedValue) * 100. "
            "Represents collection performance as a percentage. "
            "0.0 when billedValue = 0."
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
        - billedValue must be >= 0.
        - actualReceiptValue must be >= 0.
        """
        errors = {}

        if self.billedValue is not None and self.billedValue < 0:
            errors["billedValue"] = (
                f"billedValue must be >= 0. Got {self.billedValue}."
            )
        if self.actualReceiptValue is not None and self.actualReceiptValue < 0:
            errors["actualReceiptValue"] = (
                f"actualReceiptValue must be >= 0. Got {self.actualReceiptValue}."
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
          variance              = billedValue - actualReceiptValue
          variancePercentage    = (variance / billedValue) * 100
          performancePercentage = (actualReceiptValue / billedValue) * 100

        Division-by-zero guard:
          When billedValue = 0, both percentage fields default to 0.0.

        Optimisation:
          On update, skip recalculation if neither billedValue nor
          actualReceiptValue has changed.
        """
        # 1. Normalize project name
        if self.projectName:
            self.projectName = self.projectName.strip()

        # 2. Optimisation: skip recalculation if base values unchanged
        if self.pk:
            try:
                old = ContractPerformance.objects.only(
                    "billedValue", "actualReceiptValue"
                ).get(pk=self.pk)
                if (
                    old.billedValue == self.billedValue
                    and old.actualReceiptValue == self.actualReceiptValue
                ):
                    # Nothing changed — skip recalculation, just save
                    self.full_clean()
                    super().save(*args, **kwargs)
                    return
            except ContractPerformance.DoesNotExist:
                pass  # New record path

        bv = self.billedValue or Decimal("0")
        arv = self.actualReceiptValue or Decimal("0")

        # 3. Auto-calculate variance
        self.variance = bv - arv

        # 4. Auto-calculate percentages (guard against division by zero)
        if bv > 0:
            self.variancePercentage = round(
                float(self.variance / bv) * 100, 2
            )
            self.performancePercentage = round(
                float(arv / bv) * 100, 2
            )
        else:
            self.variancePercentage = 0.0
            self.performancePercentage = 0.0

        # 5. Validate before persisting
        self.full_clean()

        super().save(*args, **kwargs)

    # =========================================================================
    # Computed properties (Python-only, not stored)
    # =========================================================================

    @property
    def collectionEfficiency(self) -> float:
        """
        Collection Efficiency = actualReceiptValue / billedValue.
        > 1.0 → over-collected.
        < 1.0 → under-collected.
        Returns 0.0 when billedValue = 0.
        """
        if not self.billedValue or self.billedValue == 0:
            return 0.0
        return round(float(self.actualReceiptValue / self.billedValue), 4)

    @property
    def performanceStatus(self) -> str:
        """
        Human-readable performance status for dashboard badges.
        Based on performancePercentage:
          >= 100  → 'excellent'
          >= 90   → 'good'
          >= 75   → 'average'
          < 75    → 'poor'
        """
        pct = self.performancePercentage
        if pct >= 100:
            return "excellent"
        elif pct >= 90:
            return "good"
        elif pct >= 75:
            return "average"
        else:
            return "poor"

    # =========================================================================
    # Meta & helpers
    # =========================================================================

    def __str__(self) -> str:
        return (
            f"{self.projectName} — "
            f"Billed={self.billedValue} / "
            f"Received={self.actualReceiptValue} "
            f"({self.performancePercentage}%)"
        )

    class Meta:
        ordering = ["projectName"]
        verbose_name = "Contract Performance"
        verbose_name_plural = "Contract Performance Records"
        indexes = [
            models.Index(
                fields=["projectName"],
                name="cp_project_name_idx",
            ),
        ]
