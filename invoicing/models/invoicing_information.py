"""
Invoicing Information Model.

Tracks billing and collection KPI data per project, per invoice type.
Supports multiple invoice types (PMC, Contractor) via a single scalable model —
no duplicate APIs needed. New types can be added to InvoiceType without any
structural changes.

Automatically computes:
  - netDue = netBilledWithoutVAT - netCollected

Designed for PMC dashboard KPI cards, invoicing tables,
payment analytics, and collection tracking.

Scalable for future additions:
  - Additional invoice types (e.g. "Subcontractor", "Consultant")
  - Monthly invoicing tracking
  - Payment history
  - Collection analytics
  - Financial reporting
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class InvoicingInformation(models.Model):
    """
    One record per (projectName, invoiceType) pair.

    The unique_together constraint on (projectName, invoiceType) ensures:
      - One PMC invoicing record per project
      - One Contractor invoicing record per project
      - Both can coexist for the same project

    Example:
      { projectName: "PMC Smart City", invoiceType: "PMC" }
      { projectName: "PMC Smart City", invoiceType: "Contractor" }
    """

    # =========================================================================
    # Invoice Type Enum
    # Adding a new type in the future only requires adding a new choice here —
    # no new model, no new API, no new migration beyond the choice change.
    # =========================================================================
    class InvoiceType(models.TextChoices):
        PMC        = "PMC",        "PMC"
        CONTRACTOR = "Contractor", "Contractor"
        # Future types can be added here, e.g.:
        # SUBCONTRACTOR = "Subcontractor", "Subcontractor"
        # CONSULTANT    = "Consultant",    "Consultant"

    # -------------------------------------------------------------------------
    # Core identifier fields
    # -------------------------------------------------------------------------
    projectName = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Project name for this invoicing record",
    )
    invoiceType = models.CharField(
        max_length=50,
        choices=InvoiceType.choices,
        db_index=True,
        help_text='Invoice type: "PMC" or "Contractor"',
    )

    # -------------------------------------------------------------------------
    # Input financial fields
    # -------------------------------------------------------------------------
    grossBilled = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Total amount billed including VAT (>= 0)",
    )
    netBilledWithoutVAT = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Net amount billed excluding VAT (>= 0)",
    )
    netCollected = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text=(
            "Amount actually collected (>= 0, "
            "cannot exceed netBilledWithoutVAT)"
        ),
    )

    # -------------------------------------------------------------------------
    # Auto-calculated field (read-only; set in save())
    # -------------------------------------------------------------------------
    netDue = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal("0.00"),
        editable=False,
        help_text=(
            "Auto-calculated: netBilledWithoutVAT - netCollected. "
            "Represents outstanding / uncollected amount."
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
        - All monetary fields must be non-negative.
        - netCollected must not exceed netBilledWithoutVAT.
        """
        errors = {}

        if self.grossBilled is not None and self.grossBilled < 0:
            errors["grossBilled"] = (
                f"grossBilled must be >= 0. Got {self.grossBilled}."
            )
        if self.netBilledWithoutVAT is not None and self.netBilledWithoutVAT < 0:
            errors["netBilledWithoutVAT"] = (
                f"netBilledWithoutVAT must be >= 0. Got {self.netBilledWithoutVAT}."
            )
        if self.netCollected is not None and self.netCollected < 0:
            errors["netCollected"] = (
                f"netCollected must be >= 0. Got {self.netCollected}."
            )

        # Cross-field: netCollected cannot exceed netBilledWithoutVAT
        if (
            self.netCollected is not None
            and self.netBilledWithoutVAT is not None
            and self.netCollected > self.netBilledWithoutVAT
        ):
            errors["netCollected"] = (
                f"netCollected ({self.netCollected}) cannot exceed "
                f"netBilledWithoutVAT ({self.netBilledWithoutVAT})."
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
        2. Auto-calculate netDue.
        3. Run full_clean() to enforce validation before persisting.

        Calculation:
          netDue = netBilledWithoutVAT - netCollected
        """
        # 1. Normalize project name
        if self.projectName:
            self.projectName = self.projectName.strip()

        net_billed = self.netBilledWithoutVAT or Decimal("0")
        net_collected = self.netCollected or Decimal("0")

        # 2. Auto-calculate netDue (can be 0 when fully collected)
        self.netDue = net_billed - net_collected

        # 3. Validate before persisting
        self.full_clean()

        super().save(*args, **kwargs)

    # =========================================================================
    # Meta & helpers
    # =========================================================================

    def __str__(self) -> str:
        return (
            f"{self.projectName} [{self.invoiceType}] — "
            f"Net Due: {self.netDue}"
        )

    class Meta:
        ordering = ["projectName", "invoiceType"]
        verbose_name = "Invoicing Information"
        verbose_name_plural = "Invoicing Information"
        # One record per (project, invoiceType) pair
        constraints = [
            models.UniqueConstraint(
                fields=["projectName", "invoiceType"],
                name="inv_unique_project_invoice_type",
            )
        ]
        indexes = [
            models.Index(
                fields=["projectName"],
                name="inv_project_name_idx",
            ),
            models.Index(
                fields=["invoiceType"],
                name="inv_invoice_type_idx",
            ),
            models.Index(
                fields=["projectName", "invoiceType"],
                name="inv_project_type_idx",
            ),
        ]
