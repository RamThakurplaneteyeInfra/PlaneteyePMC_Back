from django.db import models
from django.core.validators import MinValueValidator


class InvoicingInformation(models.Model):
    """
    Invoicing Information Model
    
    Tracks billing and collection information for projects.
    - Gross Billed: Total amount billed including VAT
    - Net Billed W/O VAT: Net amount billed excluding VAT
    - Net Collected: Amount actually collected
    - Net Due: Outstanding amount (Net Billed W/O VAT - Net Collected)
    
    Access Control:
    - Billing Site Engineer can view and edit
    """
    
    project_name = models.CharField(max_length=255, db_index=True, help_text="Project name for this invoicing record")
    
    # Use Decimal for money to avoid float rounding issues
    gross_billed = models.DecimalField(
        max_digits=18, 
        decimal_places=2, 
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Total amount billed including VAT"
    )
    
    net_billed_without_vat = models.DecimalField(
        max_digits=18, 
        decimal_places=2, 
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Net amount billed excluding VAT"
    )
    
    net_collected = models.DecimalField(
        max_digits=18, 
        decimal_places=2, 
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Amount actually collected"
    )
    
    # Calculated field: net_billed_without_vat - net_collected
    net_due = models.DecimalField(
        max_digits=18, 
        decimal_places=2, 
        default=0,
        help_text="Outstanding amount (calculated: Net Billed W/O VAT - Net Collected)"
    )
    
    # Tracking fields
    created_by = models.CharField(max_length=255, help_text="User who created this record")
    updated_by = models.CharField(max_length=255, null=True, blank=True, help_text="User who last updated this record")
    
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["project_name", "-created_at"]),
            models.Index(fields=["project_name", "created_at"]),
        ]
        verbose_name = "Invoicing Information"
        verbose_name_plural = "Invoicing Information"
    
    def __str__(self) -> str:
        return f"{self.project_name} - Net Due: {self.net_due}"
    
    def save(self, *args, **kwargs):
        """
        Auto-calculate net_due before saving.
        net_due = net_billed_without_vat - net_collected
        Only recalculate if relevant fields have changed.
        """
        # Normalize project_name
        if self.project_name:
            self.project_name = self.project_name.strip()

        # Only recalculate if this is a new instance or relevant fields have changed
        if self.pk is None:
            # New instance, always calculate
            self.net_due = self.net_billed_without_vat - self.net_collected
        else:
            # Existing instance, check if calculation fields changed
            try:
                old_instance = InvoicingInformation.objects.get(pk=self.pk)
                if (old_instance.net_billed_without_vat != self.net_billed_without_vat or
                    old_instance.net_collected != self.net_collected):
                    self.net_due = self.net_billed_without_vat - self.net_collected
            except InvoicingInformation.DoesNotExist:
                # Fallback to always calculate if instance not found
                self.net_due = self.net_billed_without_vat - self.net_collected

        super().save(*args, **kwargs)
