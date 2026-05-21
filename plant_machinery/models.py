from django.db import models
from django.core.validators import MinValueValidator


class PlantMachineryReport(models.Model):
    """
    Main report for Plant & Machinery inventory at a site for a specific date.
    One report per (project_name, report_date) combination.
    """
    project_name = models.CharField(max_length=255, db_index=True)
    report_date = models.DateField(db_index=True)
    created_by = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-report_date', '-created_at']
        verbose_name = "Plant & Machinery Report"
        verbose_name_plural = "Plant & Machinery Reports"
        unique_together = [['project_name', 'report_date']]
        indexes = [
            models.Index(fields=['project_name', 'report_date']),
            models.Index(fields=['-report_date']),
        ]

    def save(self, *args, **kwargs):
        if self.project_name:
            self.project_name = self.project_name.strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.project_name} - {self.report_date}"


class MachineryItem(models.Model):
    """
    Individual machinery / equipment line item inside a PlantMachineryReport.
    """
    STATUS_CHOICES = [
        ('Working', 'Working'),
        ('Under Maintenance', 'Under Maintenance'),
        ('Not Available', 'Not Available'),
    ]

    report = models.ForeignKey(
        PlantMachineryReport,
        related_name='machinery_items',
        on_delete=models.CASCADE
    )
    sr_no = models.IntegerField()
    particular = models.CharField(max_length=255)
    unit = models.CharField(max_length=50)
    qty = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Quantity cannot be negative"
    )
    remark = models.TextField(blank=True, null=True)
    status = models.CharField(
        max_length=50,
        choices=STATUS_CHOICES,
        default='Working'
    )
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sr_no']
        verbose_name = "Machinery Item"
        verbose_name_plural = "Machinery Items"
        # Prevent duplicate sr_no within the same report
        unique_together = [['report', 'sr_no']]
        indexes = [
            models.Index(fields=['report', 'sr_no']),
        ]

    def save(self, *args, **kwargs):
        if self.particular:
            self.particular = self.particular.strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.sr_no}. {self.particular} ({self.status}) - Qty: {self.qty}"
