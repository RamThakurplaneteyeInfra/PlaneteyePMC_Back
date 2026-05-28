"""
Drawing Management Model.

Tracks drawing submission and approval counts per project.
Automatically computes:
  - variance            = totalSubmitted - totalApproved
  - approvalPercentage  = (totalApproved / totalSubmitted) * 100

Designed for PMC dashboard KPI integration.
Scalable for future additions:
  - pending drawings
  - drawing revisions
  - discipline-wise drawings
  - monthly progress tracking
  - drawing status analytics
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Drawing(models.Model):
    """
    One record per project capturing drawing submission/approval KPIs.

    Calculated fields (variance, approvalPercentage) are stored in the DB
    so dashboard queries never need to compute them on the fly.
    """

    # -------------------------------------------------------------------------
    # Core fields
    # -------------------------------------------------------------------------
    projectName = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="Unique project name for this drawing record",
    )
    totalSubmitted = models.PositiveIntegerField(
        default=0,
        help_text="Total number of drawings submitted",
    )
    totalApproved = models.PositiveIntegerField(
        default=0,
        help_text="Total number of drawings approved (cannot exceed totalSubmitted)",
    )

    # -------------------------------------------------------------------------
    # Auto-calculated fields (read-only; set in save())
    # -------------------------------------------------------------------------
    variance = models.IntegerField(
        default=0,
        editable=False,
        help_text="Auto-calculated: totalSubmitted - totalApproved",
    )
    approvalPercentage = models.FloatField(
        default=0.0,
        editable=False,
        help_text="Auto-calculated: (totalApproved / totalSubmitted) * 100",
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
        Ensures totalApproved never exceeds totalSubmitted.
        Called automatically by full_clean() before save().
        """
        if self.totalApproved is not None and self.totalSubmitted is not None:
            if self.totalApproved > self.totalSubmitted:
                raise ValidationError(
                    {
                        "totalApproved": (
                            "totalApproved cannot be greater than totalSubmitted. "
                            f"Got totalApproved={self.totalApproved}, "
                            f"totalSubmitted={self.totalSubmitted}."
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
        2. Auto-calculate variance and approvalPercentage.
        3. Run full_clean() to enforce cross-field validation.
        """
        # Normalize project name
        if self.projectName:
            self.projectName = self.projectName.strip()

        # Auto-calculate variance
        self.variance = (self.totalSubmitted or 0) - (self.totalApproved or 0)

        # Auto-calculate approval percentage (guard against division by zero)
        if self.totalSubmitted and self.totalSubmitted > 0:
            raw = (self.totalApproved / self.totalSubmitted) * 100
            # Round to 2 decimal places for clean dashboard display
            self.approvalPercentage = round(raw, 2)
        else:
            self.approvalPercentage = 0.0

        # Validate before persisting
        self.full_clean()

        super().save(*args, **kwargs)

    # =========================================================================
    # Meta & helpers
    # =========================================================================

    def __str__(self) -> str:
        return f"{self.projectName} — {self.totalApproved}/{self.totalSubmitted} approved"

    class Meta:
        ordering = ["projectName"]
        verbose_name = "Drawing"
        verbose_name_plural = "Drawings"
        indexes = [
            models.Index(fields=["projectName"], name="drawing_project_name_idx"),
        ]
