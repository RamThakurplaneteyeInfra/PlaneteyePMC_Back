from django.db import models
from django.core.validators import MinValueValidator


class ManpowerRecord(models.Model):
    """
    Monthly manpower record for a project.
    Stores planned vs actual manpower with auto-calculated difference.
    """

    project_name = models.CharField(max_length=255, db_index=True)
    month = models.CharField(max_length=20)  # e.g. "January", "May", "2026-05"
    year = models.IntegerField(db_index=True)

    monthly_planned_manpower = models.IntegerField(
        validators=[MinValueValidator(0)],
        help_text="Planned manpower for the month (cannot be negative)"
    )
    actual_manpower = models.IntegerField(
        validators=[MinValueValidator(0)],
        help_text="Actual manpower deployed (cannot be negative)"
    )
    difference = models.IntegerField(
        editable=False,
        help_text="Auto-calculated: actual_manpower - monthly_planned_manpower"
    )

    remarks = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Manpower Record"
        verbose_name_plural = "Manpower Records"
        unique_together = [['project_name', 'month', 'year']]
        indexes = [
            models.Index(fields=['project_name', 'year', 'month']),
            models.Index(fields=['-created_at']),
        ]

    def save(self, *args, **kwargs):
        # Auto-calculate difference
        self.difference = self.actual_manpower - self.monthly_planned_manpower

        # Normalize project_name
        if self.project_name:
            self.project_name = self.project_name.strip()

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.project_name} - {self.month} {self.year} (Planned: {self.monthly_planned_manpower}, Actual: {self.actual_manpower})"
