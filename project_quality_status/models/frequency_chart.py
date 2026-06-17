"""
Frequency chart / material testing register — per-item bill-period rows.

ProjectQualityStatus remains the monthly project-level KPI aggregate.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Max
from django.utils import timezone


class TestFrequencyMaster(models.Model):
    """
    Frequency rule master (e.g. 1 test per 30 Cum).

    frequency_display is the human label; frequency_value / frequency_quantity
    drive required-test calculations:
        required = ceil(qty * frequency_value / frequency_quantity)
    """

    projectName = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_index=True,
        help_text="Blank = global template; otherwise project-specific rule",
    )
    item_description = models.CharField(max_length=500, db_index=True)
    type_of_test = models.CharField(max_length=255, db_index=True)
    unit = models.CharField(max_length=50, default="")
    frequency_value = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        default=1,
        help_text="Tests numerator (e.g. 1 in '1 test / 30 cum')",
    )
    frequency_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        default=1,
        help_text="Quantity denominator (e.g. 30 in '1 test / 30 cum')",
    )
    frequency_display = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Display label e.g. '1 Test / 30 Cum'",
    )
    is_archived = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["item_description", "type_of_test"]
        verbose_name = "Test Frequency Master"
        verbose_name_plural = "Test Frequency Masters"
        indexes = [
            models.Index(
                fields=["projectName", "item_description"],
                name="freq_master_proj_item_idx",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self.frequency_display:
            fv = self.frequency_value
            fq = self.frequency_quantity
            unit = self.unit or "Unit"
            self.frequency_display = f"{fv:g} Test / {fq:g} {unit}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.item_description} — {self.type_of_test}"


class FrequencyChartEntry(models.Model):
    """One frequency-chart row for a project bill period (month/year)."""

    projectName = models.CharField(max_length=255, db_index=True)
    month = models.PositiveSmallIntegerField(db_index=True)
    year = models.PositiveSmallIntegerField(db_index=True)
    sr_no = models.PositiveIntegerField()
    item_description = models.CharField(max_length=500)
    type_of_test = models.CharField(max_length=255, db_index=True)
    unit = models.CharField(max_length=50, default="")
    activity_name = models.CharField(max_length=255, blank=True, default="", db_index=True)
    contractor_name = models.CharField(max_length=255, blank=True, default="", db_index=True)

    frequency_master = models.ForeignKey(
        TestFrequencyMaster,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chart_entries",
    )
    frequency_value = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    frequency_quantity = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    frequency_display = models.CharField(max_length=255, blank=True, default="")

    qty_previous_bill = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    qty_this_bill = models.DecimalField(max_digits=14, decimal_places=3, default=0)

    field_lab_previous_bill = models.PositiveIntegerField(default=0)
    field_lab_this_bill = models.PositiveIntegerField(default=0)
    third_party_previous_bill = models.PositiveIntegerField(default=0)
    third_party_this_bill = models.PositiveIntegerField(default=0)

    remarks = models.CharField(max_length=255, blank=True, default="")
    is_archived = models.BooleanField(default=False, db_index=True)

    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["projectName", "year", "month", "sr_no"]
        verbose_name = "Frequency Chart Entry"
        verbose_name_plural = "Frequency Chart Entries"
        constraints = [
            models.UniqueConstraint(
                fields=["projectName", "year", "month", "sr_no"],
                name="freq_chart_unique_proj_period_sr",
            ),
        ]
        indexes = [
            models.Index(
                fields=["projectName", "year", "month"],
                name="freq_chart_proj_period_idx",
            ),
            models.Index(
                fields=["projectName", "type_of_test"],
                name="freq_chart_proj_test_idx",
            ),
        ]

    @classmethod
    def next_sr_no(cls, project_name: str, month: int, year: int) -> int:
        current = cls.objects.filter(
            projectName__iexact=project_name.strip(),
            month=month,
            year=year,
        ).aggregate(max_sr=Max("sr_no"))["max_sr"]
        return (current or 0) + 1

    def clean(self):
        errors = {}
        if not (1 <= self.month <= 12):
            errors["month"] = "month must be between 1 and 12."
        if not (2000 <= self.year <= 2100):
            errors["year"] = "year must be between 2000 and 2100."
        for field in (
            "field_lab_previous_bill",
            "field_lab_this_bill",
            "third_party_previous_bill",
            "third_party_this_bill",
        ):
            if getattr(self, field) < 0:
                errors[field] = f"{field} must be >= 0."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.projectName = (self.projectName or "").strip()
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.projectName} ({self.month:02d}/{self.year}) "
            f"#{self.sr_no} {self.item_description}"
        )
