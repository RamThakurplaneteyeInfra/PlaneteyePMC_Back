"""
Invoicing Information Model.

One record per (project_name, invoice_type) — SCL or CONTRACTOR.
difference and certification_efficiency are computed in the serializer (not stored).
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class InvoicingInformation(models.Model):
    """
    Project-wise invoicing KPIs per type (SCL / CONTRACTOR).

    difference = gross_billed - gross_certified_billed
    certification_efficiency = (gross_certified_billed / gross_billed) * 100
    """

    class InvoiceType(models.TextChoices):
        SCL = "SCL", "SCL"
        CONTRACTOR = "CONTRACTOR", "CONTRACTOR"

    project_name = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Project name for this invoicing record",
    )
    invoice_type = models.CharField(
        max_length=50,
        choices=InvoiceType.choices,
        db_index=True,
        help_text='Invoice type: "SCL" or "CONTRACTOR"',
    )

    gross_billed = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Gross billed amount (>= 0)",
    )
    gross_certified_billed = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Gross certified billed amount (>= 0)",
    )

    created_at = models.DateTimeField(
        default=timezone.now,
        editable=False,
        db_index=True,
    )
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        errors = {}
        for field in ("gross_billed", "gross_certified_billed"):
            value = getattr(self, field)
            if value is not None and value < 0:
                errors[field] = f"{field} must be >= 0."

        if self.invoice_type and self.invoice_type not in {
            self.InvoiceType.SCL,
            self.InvoiceType.CONTRACTOR,
        }:
            errors["invoice_type"] = "invoice_type must be SCL or CONTRACTOR."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.project_name:
            self.project_name = self.project_name.strip()
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.project_name} [{self.invoice_type}]"

    class Meta:
        ordering = ["project_name", "invoice_type"]
        verbose_name = "Invoicing Information"
        verbose_name_plural = "Invoicing Information"
        constraints = [
            models.UniqueConstraint(
                fields=["project_name", "invoice_type"],
                name="inv_unique_project_invoice_type",
            )
        ]
        indexes = [
            models.Index(fields=["project_name"], name="inv_project_name_idx"),
            models.Index(fields=["invoice_type"], name="inv_invoice_type_idx"),
            models.Index(
                fields=["project_name", "invoice_type"],
                name="inv_project_type_idx",
            ),
        ]
