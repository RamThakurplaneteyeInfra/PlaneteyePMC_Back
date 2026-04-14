# Health & Safety Models
from django.db import models
from django.core.validators import MinValueValidator


class HealthSafetyReport(models.Model):
    """
    Health & Safety Status Report
    Stores incident data and manhours for safety analysis
    """
    project_name = models.CharField(max_length=255, db_index=True, help_text="Name of the project")
    report_date = models.DateField(help_text="Date of the report")
    total_manhours = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text="Total manhours worked"
    )
    
    # Incident counts
    fatalities = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Number of fatalities"
    )
    significant = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Number of significant incidents"
    )
    major = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Number of major incidents"
    )
    minor = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Number of minor incidents"
    )
    near_miss = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Number of near miss incidents"
    )
    
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-report_date', '-created_at']
        verbose_name = "Health & Safety Report"
        verbose_name_plural = "Health & Safety Reports"
        indexes = [
            models.Index(fields=['project_name', '-report_date']),
            models.Index(fields=['-report_date']),
        ]
        constraints = [
            models.UniqueConstraint(fields=['project_name', 'report_date'], name='unique_project_date_hs'),
        ]

    def save(self, *args, **kwargs):
        # Normalize project_name by stripping whitespace
        if self.project_name:
            self.project_name = self.project_name.strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"H&S - {self.project_name} ({self.report_date})"

    @property
    def total_incidents(self):
        """Calculate total incidents"""
        return self.fatalities + self.significant + self.major + self.minor + self.near_miss
