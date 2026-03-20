from django.db import models
from django.contrib.auth.models import User
from projects.models import Site, Project

class Task(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('delayed', 'Delayed'),
    ]

    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='tasks')
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_tasks')
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    progress_percentage = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.site.name} - {self.name}"

class DailyProgressReport(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='daily_reports', null=True, blank=True)
    # Adding site and project for flexible reporting
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='dprs', null=True, blank=True)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='dprs', null=True, blank=True)
    submitted_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='submitted_reports')
    report_date = models.DateField()
    work_done = models.TextField()
    
    # New fields to match frontend requirements
    labor_log = models.JSONField(default=dict, blank=True)
    machinery_log = models.JSONField(default=list, blank=True)
    activity_progress = models.JSONField(default=list, blank=True)
    manpower_count = models.IntegerField(default=0)
    critical_issues = models.TextField(blank=True)
    billing_status = models.CharField(max_length=100, blank=True, null=True)
    
    # Review status
    status = models.CharField(max_length=20, choices=[('PENDING', 'Pending'), ('APPROVED', 'Approved'), ('REJECTED', 'Rejected')], default='PENDING')
    rejection_reason = models.TextField(blank=True)
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_reports')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"DPR - {self.report_date} ({self.submitted_by.username})"
