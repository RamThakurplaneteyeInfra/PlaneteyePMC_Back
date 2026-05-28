"""
Contract Value Model.

Stores financial contract KPI data per project, per contract type.
Supports multiple contract types (SCL, Contractor) via a single scalable model —
no duplicate APIs needed. New types can be added to ContractType without any
structural changes.

Automatically computes:
  - approvedVOPercentage  = (approvedVO / originalContractValue) * 100
  - revisedContractValue  = originalContractValue + approvedVO

Designed for PMC dashboard KPI cards, contract comparison tables,
and financial tracking charts.

Scalable for future additions:
  - Additional contract types (e.g. "Subcontractor", "Consultant")
  - Monthly contract value tracking
  - Baseline comparison
  - Forecasting analytics
  - Contract health indicators
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class ContractValue(models.Model):
    """
    One record per (projectName, contractType) pair.

    The unique_together constraint on (projectName, contractType) ensures:
      - One SCL record per project
      - One Contractor record per project
      - Both can coexist for the same project

    Example:
      { projectName: "PMC Smart City", contractType: "SCL" }
      { projectName: "PMC Smart City", contractType: "Contractor" }
    """

    # =========================================================================
    # Contract Type Enum
    # Adding a new type in the future only requires adding a new choice here —
    # no new model, no new API, no new migration beyond the choice change.
    # =========================================================================
    class ContractType(models.TextChoices):
        SCL        = "SCL",        "SCL"
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
        help_text="Project name for this contract value record",
    )
    contractType = models.CharField(
        max_length=50,
        choices=ContractType.choices,
        db_index=True,
        help_text='Contract type: "SCL" or "Contractor"',
    )

    # -------------------------------------------------------------------------
    # Input financial fields
    # -------------------------------------------------------------------------
    originalContractValue = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Original contract value (>= 0)",
    )
    approvedVO = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Approved Variation Order amount (>= 0)",
    )
    potentialPendingVO = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Potential / Pending Variation Order amount (>= 0)",
    )

    # -------------------------------------------------------------------------
    # Auto-calculated fields (read-only; set in save())
    # -------------------------------------------------------------------------
    approvedVOPercentage = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        editable=False,
        help_text=(
            "Auto-calculated: (approvedVO / originalContractValue) * 100. "
            "0.00 when originalContractValue = 0."
        ),
    )
    revisedContractValue = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal("0.00"),
        editable=False,
        help_text="Auto-calculated: originalContractValue + approvedVO",
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
        All monetary fields must be non-negative.
        """
        errors = {}

        if self.originalContractValue is not None and self.originalContractValue < 0:
            errors["originalContractValue"] = (
                f"originalContractValue must be >= 0. Got {self.originalContractValue}."
            )
        if self.approvedVO is not None and self.approvedVO < 0:
            errors["approvedVO"] = (
                f"approvedVO must be >= 0. Got {self.approvedVO}."
            )
        if self.potentialPendingVO is not None and self.potentialPendingVO < 0:
            errors["potentialPendingVO"] = (
                f"potentialPendingVO must be >= 0. Got {self.potentialPendingVO}."
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
        2. Auto-calculate revisedContractValue and approvedVOPercentage.
        3. Run full_clean() to enforce field validation before persisting.

        Calculation rules:
          revisedContractValue  = originalContractValue + approvedVO
          approvedVOPercentage  = (approvedVO / originalContractValue) * 100

        Division-by-zero guard:
          When originalContractValue = 0, approvedVOPercentage defaults to 0.00.
        """
        # 1. Normalize project name
        if self.projectName:
            self.projectName = self.projectName.strip()

        ocv = self.originalContractValue or Decimal("0")
        avo = self.approvedVO or Decimal("0")

        # 2. Auto-calculate revised contract value
        self.revisedContractValue = ocv + avo

        # 3. Auto-calculate approved VO percentage (guard against division by zero)
        if ocv > 0:
            self.approvedVOPercentage = round(
                (avo / ocv) * Decimal("100"), 2
            )
        else:
            self.approvedVOPercentage = Decimal("0.00")

        # 4. Validate before persisting
        self.full_clean()

        super().save(*args, **kwargs)

    # =========================================================================
    # Meta & helpers
    # =========================================================================

    def __str__(self) -> str:
        return (
            f"{self.projectName} [{self.contractType}] — "
            f"OCV={self.originalContractValue} / "
            f"RCV={self.revisedContractValue}"
        )

    class Meta:
        ordering = ["projectName", "contractType"]
        verbose_name = "Contract Value"
        verbose_name_plural = "Contract Values"
        # One record per (project, contractType) pair
        constraints = [
            models.UniqueConstraint(
                fields=["projectName", "contractType"],
                name="cv_unique_project_contract_type",
            )
        ]
        indexes = [
            models.Index(
                fields=["projectName"],
                name="cv_project_name_idx",
            ),
            models.Index(
                fields=["contractType"],
                name="cv_contract_type_idx",
            ),
            models.Index(
                fields=["projectName", "contractType"],
                name="cv_project_type_idx",
            ),
        ]
