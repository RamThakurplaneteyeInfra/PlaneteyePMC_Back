from django.db import models
from django.contrib.auth.models import User

class Project(models.Model):
    STATUS_CHOICES = [
        ('planning', 'Planning'),
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('on_hold', 'On Hold'),
    ]

    name = models.CharField(max_length=255)
    client_name = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    location = models.CharField(max_length=255, blank=True)
    commencement_date = models.DateField(null=True, blank=True)
    duration = models.CharField(max_length=100, blank=True)
    budget = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    salient_features = models.TextField(blank=True)
    site_staff_details = models.TextField(blank=True)
    
    # Requirement Toggles
    has_documentation = models.BooleanField(default=False)
    documentation_file = models.FileField(upload_to='project_docs/', null=True, blank=True)
    has_iso_checklist = models.BooleanField(default=False)
    has_test_frequency_chart = models.BooleanField(default=False)

    # User Assignments
    pmc_head = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='pmc_projects')
    team_lead = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='lead_projects')
    site_engineers = models.ManyToManyField(User, blank=True, related_name='assigned_projects')
    coordinators = models.ManyToManyField(User, blank=True, related_name='coordinator_projects')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_projects')

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='planning')
    start_date = models.DateField(null=True, blank=True) # Keeping for compatibility
    end_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

class Site(models.Model):
    STATUS_CHOICES = [
        ('not_started', 'Not Started'),
        ('active', 'Active'),
        ('completed', 'Completed'),
    ]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='sites')
    name = models.CharField(max_length=255)
    location = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='not_started')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.project.name} - {self.name}"


class ProjectDashboardData(models.Model):
    """Stores dashboard metrics for projects"""
    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name='dashboard_data')
    
    # Financial Metrics
    planned_value = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    earned_value = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    bcwp = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    ac = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    actual_billed = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    
    # Contract Values
    original_contract_value = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    approved_vo = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    revised_contract_value = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    pending_vo = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    
    # Invoicing
    gross_billed = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    net_billed = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    net_collected = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    net_due = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    
    # Project Dates
    project_start_date = models.DateField(null=True, blank=True)
    contract_finish_date = models.DateField(null=True, blank=True)
    forecast_finish_date = models.DateField(null=True, blank=True)
    delay_days = models.IntegerField(null=True, blank=True)
    
    # Safety Metrics
    fatalities = models.IntegerField(default=0)
    significant = models.IntegerField(default=0)
    major = models.IntegerField(default=0)
    minor = models.IntegerField(default=0)
    near_miss = models.IntegerField(default=0)
    total_manhours = models.BigIntegerField(null=True, blank=True)
    loss_of_manhours = models.BigIntegerField(null=True, blank=True)
    
    # Additional JSON field for flexible data storage
    additional_data = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Project Dashboard Data"
        verbose_name_plural = "Project Dashboard Data"
    
    def __str__(self):
        return f"Dashboard Data for {self.project.name}"

