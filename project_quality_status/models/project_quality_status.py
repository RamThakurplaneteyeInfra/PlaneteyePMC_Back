"""
Project Quality Status Model.

Tracks quality testing KPIs per project.
Automatically computes:
  - variance              = totalTestsConducted - totalTestsPassed
  - performancePercentage = (totalTestsPassed / totalTestsConducted) * 100

Key design decisions:
  - totalTestsPassed cannot exceed totalTestsConducted.
  - Both values must be non-negative integers.
  - Division-by-zero is handled: performancePercentage defaults to 0.0
    when totalTestsConducted = 0.
  - Percentages are rounded to 2 decimal places.
  - One record per project (unique on projectName).

Designed for PMC dashboard KPI cards, quality performance gauges,
and project health monitoring.

Scalable for future additions:
  - Category-wise tests (structural, electrical, civil …)
  - Monthly quality tracking
  - Failed test history
  - QA/QC reports and compliance analytics
  - Quality trends and forecasting
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class ProjectQualityStatus(models.Model):
    """
    One record per project capturing quality testing KPIs.

    Calculated fields (variance, performancePercentage) are stored in the DB
    so dashboard queries never need to compute them on the fly.
    """

    # -------------------------------------------------------------------------
    # Core identifier
    # -------------------------------------------------------------------------
    projectName = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="Unique project name for this quality status record",
    )

    # -------------------------------------------------------------------------
    # Input fields
    # -------------------------------------------------------------------------
    totalTestsConducted = models.PositiveIntegerField(
        default=0,
        help_text="Total number of quality tests conducted",
    )
    totalTestsPassed = models.PositiveIntegerField(
        default=0,
        help_text=(
            "Total number of quality tests passed "
            "(cannot exceed totalTestsConducted)"
        ),
    )

    # -------------------------------------------------------------------------
    # Auto-calculated fields (read-only; set in save())
    # -------------------------------------------------------------------------
    variance = models.IntegerField(
        default=0,
        editable=False,
        help_text=(
            "Auto-calculated: totalTestsConducted - totalTestsPassed. "
            "Represents the number of failed / pending tests."
        ),
    )
    performancePercentage = models.FloatField(
        default=0.0,
        editable=False,
        help_text=(
            "Auto-calculated: (totalTestsPassed / totalTestsConducted) * 100. "
            "0.0 when totalTestsConducted = 0."
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
        Cross-field validation.
        totalTestsPassed must not exceed totalTestsConducted.
        """
        conducted = self.totalTestsConducted
        passed = self.totalTestsPassed

        if conducted is not None and passed is not None:
            if passed > conducted:
                raise ValidationError(
                    {
                        "totalTestsPassed": (
                            "totalTestsPassed cannot be greater than "
                            "totalTestsConducted. "
                            f"Got totalTestsPassed={passed}, "
                            f"totalTestsConducted={conducted}."
                        )
                    }
                )

    # =========================================================================
    # Auto-calculation on save
    # =========================================================================

    def save(self, *args, **kwargs):
        """
        Override save to:
        1. Normalize projectName (strip whitespace).
        2. Auto-calculate variance and performancePercentage.
        3. Run full_clean() to enforce cross-field validation.
        """
        # 1. Normalize project name
        if self.projectName:
            self.projectName = self.projectName.strip()

        conducted = self.totalTestsConducted or 0
        passed = self.totalTestsPassed or 0

        # 2. Auto-calculate variance (failed / pending tests)
        self.variance = conducted - passed

        # 3. Auto-calculate performance percentage (guard division by zero)
        if conducted > 0:
            self.performancePercentage = round((passed / conducted) * 100, 2)
        else:
            self.performancePercentage = 0.0

        super().save(*args, **kwargs)

    # =========================================================================
    # Computed properties (Python-only, not stored)
    # =========================================================================

    @property
    def qualityStatus(self) -> str:
        """
        Human-readable quality status for dashboard badges.
        Based on performancePercentage:
          >= 95  → 'excellent'
          >= 80  → 'good'
          >= 60  → 'average'
          < 60   → 'poor'
        """
        pct = self.performancePercentage
        if pct >= 95:
            return "excellent"
        elif pct >= 80:
            return "good"
        elif pct >= 60:
            return "average"
        else:
            return "poor"

    @property
    def failedTests(self) -> int:
        """Alias for variance — number of tests that did not pass."""
        return self.variance

    # =========================================================================
    # Meta & helpers
    # =========================================================================

    def __str__(self) -> str:
        return (
            f"{self.projectName} — "
            f"{self.totalTestsPassed}/{self.totalTestsConducted} passed "
            f"({self.performancePercentage}%)"
        )

    class Meta:
        ordering = ["projectName"]
        verbose_name = "Project Quality Status"
        verbose_name_plural = "Project Quality Status Records"
        indexes = [
            models.Index(
                fields=["projectName"],
                name="pqs_project_name_idx",
            ),
        ]
