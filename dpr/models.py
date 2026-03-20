from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator


class DailyProgressReport(models.Model):
    """
    Main Daily Progress Report model
    Stores the primary report information
    """
    project_name = models.CharField(max_length=255, help_text="Name of the project")
    job_no = models.CharField(max_length=100, help_text="Job number or reference code")
    report_date = models.DateField(help_text="Date of the report")
    unresolved_issues = models.TextField(blank=True, help_text="Any unresolved issues")
    pending_letters = models.TextField(blank=True, help_text="Pending letters or communications")
    quality_status = models.TextField(blank=True, help_text="Quality status information")
    next_day_incident = models.TextField(blank=True, help_text="Incidents planned for next day")
    bill_status = models.TextField(blank=True, help_text="Billing status")
    gfc_status = models.TextField(blank=True, help_text="GFC (Good for Construction) status")
    issued_by = models.CharField(max_length=255, help_text="Person who issued the report")
    designation = models.CharField(max_length=255, help_text="Designation of the issuer")
    created_at = models.DateTimeField(auto_now_add=True, help_text="Timestamp when report was created")
    updated_at = models.DateTimeField(auto_now=True, help_text="Timestamp when report was last updated")

    class Meta:
        ordering = ['-report_date', '-created_at']  # Latest first
        verbose_name = "Daily Progress Report"
        verbose_name_plural = "Daily Progress Reports"
        indexes = [
            models.Index(fields=['project_name', '-report_date']),
            models.Index(fields=['-report_date']),
        ]

    def __str__(self):
        return f"DPR - {self.project_name} ({self.report_date})"


class DPRActivity(models.Model):
    """
    Activity details within a Daily Progress Report
    Each report can have multiple activities
    """
    dpr = models.ForeignKey(
        DailyProgressReport,
        on_delete=models.CASCADE,
        related_name='activities',
        help_text="Parent Daily Progress Report"
    )
    date = models.DateField(help_text="Date of the activity")
    activity = models.TextField(help_text="Description of the activity")
    deliverables = models.TextField(blank=True, help_text="Deliverables for this activity")
    target_achieved = models.FloatField(
        default=0.0,
        validators=[MinValueValidator(0.0), MaxValueValidator(100.0)],
        help_text="Target achieved percentage (0-100)"
    )
    next_day_plan = models.TextField(blank=True, help_text="Plan for the next day")
    remarks = models.TextField(blank=True, help_text="Additional remarks")

    class Meta:
        ordering = ['date', 'id']
        verbose_name = "DPR Activity"
        verbose_name_plural = "DPR Activities"

    def __str__(self):
        return f"Activity - {self.activity[:50]} ({self.date})"
