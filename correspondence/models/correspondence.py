"""
Correspondence & Delivery Status Model.

Tracks inward/outward correspondence counts per project.
Automatically computes:
  - pendingCorrespondence  = correspondenceReceived - correspondenceDelivered
  - deliveryPercentage     = (correspondenceDelivered / correspondenceReceived) * 100

Designed for PMC dashboard KPI card integration.

Scalable for future additions:
  - monthly correspondence tracking
  - inward / outward correspondence history
  - document categories (letters, memos, RFIs, submittals …)
  - priority levels (urgent, normal, low)
  - overdue correspondence tracking
  - project-wise delivery analytics
  - charts and dashboard visualisation
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Correspondence(models.Model):
    """
    One cumulative record per project capturing correspondence delivery KPIs.

    Calculated fields (pendingCorrespondence, deliveryPercentage) are stored
    in the DB so dashboard queries never need to compute them on the fly.
    """

    # -------------------------------------------------------------------------
    # Core fields
    # -------------------------------------------------------------------------
    projectName = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="Unique project name for this correspondence record",
    )
    correspondenceReceived = models.PositiveIntegerField(
        default=0,
        help_text="Total correspondence items received",
    )
    correspondenceDelivered = models.PositiveIntegerField(
        default=0,
        help_text=(
            "Total correspondence items delivered "
            "(cannot exceed correspondenceReceived)"
        ),
    )

    # -------------------------------------------------------------------------
    # Auto-calculated fields (read-only; set in save())
    # -------------------------------------------------------------------------
    pendingCorrespondence = models.IntegerField(
        default=0,
        editable=False,
        help_text="Auto-calculated: correspondenceReceived - correspondenceDelivered",
    )
    deliveryPercentage = models.FloatField(
        default=0.0,
        editable=False,
        help_text=(
            "Auto-calculated: "
            "(correspondenceDelivered / correspondenceReceived) * 100"
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
        Ensures correspondenceDelivered never exceeds correspondenceReceived.
        Called automatically by full_clean() before save().
        """
        received = self.correspondenceReceived
        delivered = self.correspondenceDelivered

        if received is not None and delivered is not None:
            if delivered > received:
                raise ValidationError(
                    {
                        "correspondenceDelivered": (
                            "correspondenceDelivered cannot be greater than "
                            "correspondenceReceived. "
                            f"Got correspondenceDelivered={delivered}, "
                            f"correspondenceReceived={received}."
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
        2. Auto-calculate pendingCorrespondence and deliveryPercentage.
        3. Run full_clean() to enforce cross-field validation.
        """
        # Normalize project name to avoid duplicates from whitespace differences
        if self.projectName:
            self.projectName = self.projectName.strip()

        received = self.correspondenceReceived or 0
        delivered = self.correspondenceDelivered or 0

        # Auto-calculate pending correspondence
        self.pendingCorrespondence = received - delivered

        # Auto-calculate delivery percentage (guard against division by zero)
        if received > 0:
            self.deliveryPercentage = round((delivered / received) * 100, 2)
        else:
            self.deliveryPercentage = 0.0

        # Validate before persisting (raises ValidationError on failure)
        self.full_clean()

        super().save(*args, **kwargs)

    # =========================================================================
    # Meta & helpers
    # =========================================================================

    def __str__(self) -> str:
        return (
            f"{self.projectName} — "
            f"{self.correspondenceDelivered}/{self.correspondenceReceived} delivered "
            f"({self.deliveryPercentage}%)"
        )

    class Meta:
        ordering = ["projectName"]
        verbose_name = "Correspondence Record"
        verbose_name_plural = "Correspondence Records"
        indexes = [
            models.Index(
                fields=["projectName"],
                name="corr_project_name_idx",
            ),
        ]
