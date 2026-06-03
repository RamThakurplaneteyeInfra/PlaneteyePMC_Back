"""
Contract Value Model.

One record per (project_name, contract_type) — SCL or CONTRACTOR.
revised_value and increase_percentage are computed in the serializer (not stored).
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class ContractValue(models.Model):
    """
    Project-wise contract financials per type (SCL / CONTRACTOR).

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
        ):
            value = getattr(self, field)
            if value is not None and value < 0:
                errors[field] = f"{field} must be >= 0."

        if self.contract_type and self.contract_type not in {
            self.ContractType.SCL,
            self.ContractType.CONTRACTOR,
        }:
            errors["contract_type"] = "contract_type must be SCL or CONTRACTOR."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.project_name:
            self.project_name = self.project_name.strip()
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return (
            f"{self.project_name} [{self.contract_type}] — "
            f"OCV={self.original_contract_value}"
        )

    class Meta:
        ordering = ["project_name", "contract_type"]
        verbose_name = "Contract Value"
        verbose_name_plural = "Contract Values"
        constraints = [
            models.UniqueConstraint(
                fields=["project_name", "contract_type"],
                name="cv_unique_project_contract_type",
            )
        ]
        indexes = [
            models.Index(fields=["project_name"], name="cv_project_name_idx"),
            models.Index(fields=["contract_type"], name="cv_contract_type_idx"),
            models.Index(fields=["project_name", "contract_type"], name="cv_project_type_idx"),
        ]
