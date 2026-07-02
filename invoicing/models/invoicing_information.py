"""
Invoicing Information Model.

One SCL record per project; multiple CONTRACTOR records per project (unique contractor_name).
difference and certification_efficiency are computed in the serializer (not stored).
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone


class InvoicingInformation(models.Model):
    """
    Project-wise invoicing KPIs per type (SCL / named CONTRACTOR).

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
        related_name="invoicing_records",
        db_index=True,
        help_text="Contractor Master reference (required for CONTRACTOR)",
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

        if self.invoice_type == self.InvoiceType.SCL:
            if self.contractor_name and str(self.contractor_name).strip():
                errors["contractor_name"] = (
                    "contractor_name must be empty for SCL records."
                )
        elif self.invoice_type == self.InvoiceType.CONTRACTOR:
            if not self.contractor_id and not (self.contractor_name or "").strip():
                errors["contractor_id"] = (
                    "contractor_id is required for CONTRACTOR records."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.project_name:
            self.project_name = self.project_name.strip()
        if self.invoice_type == self.InvoiceType.SCL:
            self.contractor_name = None
            self.contractor = None
        elif self.contractor_id:
            self.contractor_name = self.contractor.contractor_name
        elif self.contractor_name:
            self.contractor_name = str(self.contractor_name).strip()
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        if self.invoice_type == self.InvoiceType.CONTRACTOR and self.contractor_name:
            return f"{self.project_name} — {self.contractor_name} [{self.invoice_type}]"
        return f"{self.project_name} [{self.invoice_type}]"

    class Meta:
        ordering = ["project_name", "invoice_type", "contractor_name"]
        verbose_name = "Invoicing Information"
        verbose_name_plural = "Invoicing Information"
        constraints = [
            models.UniqueConstraint(
                fields=["project_name", "invoice_type"],
                condition=Q(invoice_type="SCL"),
                name="inv_unique_scl_per_project",
            ),
            models.UniqueConstraint(
                fields=["project_name", "contractor"],
                condition=Q(invoice_type="CONTRACTOR"),
                name="inv_unique_contractor_per_project",
            ),
        ]
        indexes = [
            models.Index(fields=["project_name"], name="inv_project_name_idx"),
            models.Index(fields=["invoice_type"], name="inv_invoice_type_idx"),
            models.Index(
                fields=["project_name", "invoice_type"],
                name="inv_project_type_idx",
            ),
            models.Index(
                fields=["project_name", "contractor_name"],
                name="inv_project_contractor_idx",
            ),
        ]
