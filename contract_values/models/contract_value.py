"""
Contract Value Model.

One SCL record per project; multiple CONTRACTOR records per project (unique contractor_name).
revised_value and increase_percentage are computed in the serializer (not stored).
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone


class ContractValue(models.Model):
    """
    Project-wise contract financials per type (SCL / named CONTRACTOR).

    revised_value = original_contract_value + excess_value - saving
    increase_percentage is derived at read time in the API layer.
    """

    class ContractType(models.TextChoices):
        SCL = "SCL", "SCL"
        CONTRACTOR = "CONTRACTOR", "CONTRACTOR"

    project_name = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Project name for this contract value record",
    )
    contract_type = models.CharField(
        max_length=50,
        choices=ContractType.choices,
        db_index=True,
        help_text='Contract type: "SCL" or "CONTRACTOR"',
    )
    contractor_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        db_index=True,
        help_text="Contractor display name (denormalized from Contractor Master)",
    )
    contractor = models.ForeignKey(
        "contractors.Contractor",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="contract_values",
        db_index=True,
        help_text="Contractor Master reference (required for CONTRACTOR)",
    )

    original_contract_value = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Original contract value (>= 0)",
    )
    excess_value = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Excess value (>= 0)",
    )
    saving = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Saving amount (>= 0)",
    )
    cos = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="COS (Change of Scope) amount (>= 0). Manually editable; not used in revised_value formula.",
    )

    created_at = models.DateTimeField(
        default=timezone.now,
        editable=False,
        db_index=True,
    )
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        errors = {}
        for field in (
            "original_contract_value",
            "excess_value",
            "saving",
            "cos",
        ):
            value = getattr(self, field)
            if value is not None and value < 0:
                errors[field] = f"{field} must be >= 0."

        if self.contract_type and self.contract_type not in {
            self.ContractType.SCL,
            self.ContractType.CONTRACTOR,
        }:
            errors["contract_type"] = "contract_type must be SCL or CONTRACTOR."

        if self.contract_type == self.ContractType.SCL:
            if self.contractor_name and str(self.contractor_name).strip():
                errors["contractor_name"] = (
                    "contractor_name must be empty for SCL records."
                )
        elif self.contract_type == self.ContractType.CONTRACTOR:
            if not self.contractor_id and not (self.contractor_name or "").strip():
                errors["contractor_id"] = (
                    "contractor_id is required for CONTRACTOR records."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.project_name:
            self.project_name = self.project_name.strip()
        if self.contract_type == self.ContractType.SCL:
            self.contractor_name = None
            self.contractor = None
        elif self.contractor_id:
            self.contractor_name = self.contractor.contractor_name
        elif self.contractor_name:
            self.contractor_name = str(self.contractor_name).strip()
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        label = self.contract_type
        if self.contract_type == self.ContractType.CONTRACTOR and self.contractor_name:
            label = f"{self.contractor_name} [{self.contract_type}]"
        return f"{self.project_name} — {label} — OCV={self.original_contract_value}"

    class Meta:
        ordering = ["project_name", "contract_type", "contractor_name"]
        verbose_name = "Contract Value"
        verbose_name_plural = "Contract Values"
        constraints = [
            models.UniqueConstraint(
                fields=["project_name", "contract_type"],
                condition=Q(contract_type="SCL"),
                name="cv_unique_scl_per_project",
            ),
            models.UniqueConstraint(
                fields=["project_name", "contractor"],
                condition=Q(contract_type="CONTRACTOR"),
                name="cv_unique_contractor_per_project",
            ),
        ]
        indexes = [
            models.Index(fields=["project_name"], name="cv_project_name_idx"),
            models.Index(fields=["contract_type"], name="cv_contract_type_idx"),
            models.Index(fields=["project_name", "contract_type"], name="cv_project_type_idx"),
            models.Index(
                fields=["project_name", "contractor_name"],
                name="cv_project_contractor_idx",
            ),
        ]
