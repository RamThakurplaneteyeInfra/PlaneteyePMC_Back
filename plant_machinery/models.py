from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class MachineryMaster(models.Model):
    """
    Global machinery catalogue — shared across all projects and reports.
    New entries are immediately available everywhere via this table.
    """

    name = models.CharField(
        max_length=255,
        unique=True,
        help_text="Unique machinery name",
    )
    unit = models.CharField(
        max_length=50,
        help_text="Unit of measure (e.g. Nos, Hour)",
    )
    category = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Machinery category",
    )
    is_default = models.BooleanField(
        default=False,
        help_text="True for system-seeded default machinery types",
    )
    created_at = models.DateTimeField(
        default=timezone.now,
        editable=False,
        db_index=True,
    )

    class Meta:
        ordering = ["name"]
        verbose_name = "Machinery Master"
        verbose_name_plural = "Machinery Master"
        indexes = [
            models.Index(fields=["name"], name="pm_master_name_idx"),
            models.Index(fields=["category"], name="pm_master_category_idx"),
        ]

    def save(self, *args, **kwargs):
        if self.name:
            self.name = self.name.strip()
        if self.category:
            self.category = self.category.strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.unit})"


class PlantMachineryReport(models.Model):
    """
    Plant & Machinery inventory report for a site on a specific date.
    One report per (project_name, report_date).
    """

    project_name = models.CharField(max_length=255, db_index=True)
    report_date = models.DateField(db_index=True)
    created_by = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-report_date", "-created_at"]
        verbose_name = "Plant & Machinery Report"
        verbose_name_plural = "Plant & Machinery Reports"
        unique_together = [["project_name", "report_date"]]
        indexes = [
            models.Index(fields=["project_name", "report_date"]),
            models.Index(fields=["-report_date"]),
        ]

    def save(self, *args, **kwargs):
        if self.project_name:
            self.project_name = self.project_name.strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.project_name} - {self.report_date}"


class MachineryItem(models.Model):
    """Machinery line item in a report — references MachineryMaster."""

    STATUS_CHOICES = [
        ("Working", "Working"),
        ("Under Maintenance", "Under Maintenance"),
        ("Not Available", "Not Available"),
    ]

    report = models.ForeignKey(
        PlantMachineryReport,
        related_name="machinery_items",
        on_delete=models.CASCADE,
    )
    machinery_master = models.ForeignKey(
        MachineryMaster,
        related_name="log_items",
        on_delete=models.PROTECT,
        help_text="Machinery type from global master catalogue",
    )
    sr_no = models.IntegerField()
    qty = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Quantity cannot be negative",
    )
    remark = models.TextField(blank=True, null=True)
    status = models.CharField(
        max_length=50,
        choices=STATUS_CHOICES,
        default="Working",
    )
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sr_no"]
        verbose_name = "Machinery Item"
        verbose_name_plural = "Machinery Items"
        unique_together = [["report", "sr_no"]]
        constraints = [
            models.UniqueConstraint(
                fields=["report", "machinery_master"],
                name="pm_unique_report_machinery_master",
            ),
        ]
        indexes = [
            models.Index(fields=["report", "sr_no"]),
            models.Index(fields=["machinery_master"]),
        ]

    @property
    def particular(self) -> str:
        return self.machinery_master.name if self.machinery_master_id else ""

    @property
    def unit(self) -> str:
        return self.machinery_master.unit if self.machinery_master_id else ""

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.sr_no}. {self.particular} ({self.status}) - Qty: {self.qty}"
