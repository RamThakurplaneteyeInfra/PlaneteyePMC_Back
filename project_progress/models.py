from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator


class ProjectProgressStatus(models.Model):
    """
    Project Progress Status Model
    
    Tracks monthly and cumulative progress for projects:
    - Monthly Plan: Planned progress for a specific month
    - Cumulative Plan: Cumulative planned progress from project start to this month
    - Monthly Actual: Actual progress achieved in a specific month
    - Cumulative Actual: Cumulative actual progress from project start to this month
    
    Used for S-curve charts and progress tracking.
    
    Access Control:
    - Billing Site Engineer can view and edit
    """
    
    project_name = models.CharField(max_length=255, help_text="Project name for this progress record")
    
    # Month/Date for this progress record (stored as first day of the month)
    progress_month = models.DateField(help_text="Month for this progress record (first day of the month)")
    
    # Monthly progress values (percentages 0-100)
    monthly_plan = models.FloatField(
        default=0.0,
        validators=[MinValueValidator(0.0), MaxValueValidator(100.0)],
        help_text="Planned progress for this month (percentage 0-100)"
    )
    
    cumulative_plan = models.FloatField(
        default=0.0,
        validators=[MinValueValidator(0.0), MaxValueValidator(100.0)],
        help_text="Cumulative planned progress from project start to this month (percentage 0-100)"
    )
    
    monthly_actual = models.FloatField(
        default=0.0,
        validators=[MinValueValidator(0.0), MaxValueValidator(100.0)],
        help_text="Actual progress achieved in this month (percentage 0-100)"
    )
    
    cumulative_actual = models.FloatField(
        default=0.0,
        validators=[MinValueValidator(0.0), MaxValueValidator(100.0)],
        help_text="Cumulative actual progress from project start to this month (percentage 0-100)"
    )
    
    # Tracking fields
    created_by = models.CharField(max_length=255, help_text="User who created this record")
    updated_by = models.CharField(max_length=255, null=True, blank=True, help_text="User who last updated this record")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ["project_name", "progress_month"]
        indexes = [
            models.Index(fields=["project_name", "progress_month"]),
            models.Index(fields=["progress_month"]),
        ]
        unique_together = [["project_name", "progress_month"]]  # One record per project per month
        verbose_name = "Project Progress Status"
        verbose_name_plural = "Project Progress Status"
    
    def __str__(self) -> str:
        from django.utils import timezone
        month_str = self.progress_month.strftime("%b-%y")
        return f"{self.project_name} - {month_str} (Plan: {self.cumulative_plan:.2f}%, Actual: {self.cumulative_actual:.2f}%)"
