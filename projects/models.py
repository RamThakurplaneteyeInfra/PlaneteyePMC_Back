from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from decimal import Decimal

# Constants
ZERO = Decimal('0.00')

class Project(models.Model):
    STATUS_CHOICES = [
        ('planning', 'Planning'),
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('on_hold', 'On Hold'),
    ]

    name = models.CharField(max_length=255, db_index=True)
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
    # Separate fields for different site engineer types
    billing_site_engineer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='billing_engineer_projects')
    qaqc_site_engineer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='qaqc_engineer_projects')
    coordinators = models.ManyToManyField(User, blank=True, related_name='coordinator_projects')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_projects')

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='planning', db_index=True)
    start_date = models.DateField(null=True, blank=True) # Keeping for compatibility
    end_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    # ==========================================================================
    # Project Initialization Fields (PMC Head Input)
    # ==========================================================================
    
    # Project Dates
    project_start = models.DateField(null=True, blank=True, help_text="Project start date")
    contract_finish = models.DateField(null=True, blank=True, help_text="Contractual finish date")
    forecast_finish = models.DateField(null=True, blank=True, help_text="Forecasted finish date")
    
    # Contract Values
    original_contract_value = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(0)],
        help_text="Original contract value"
    )
    approved_vo = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(0)],
        help_text="Approved Variation Order"
    )
    pending_vo = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(0)],
        help_text="Pending Variation Order"
    )
    
    # Budget
    bac = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(0)],
        help_text="Budget at Completion"
    )
    
    # Work Configuration
    working_hours_per_day = models.FloatField(
        default=8.0,
        validators=[MinValueValidator(0)],
        help_text="Working hours per day"
    )
    working_days_per_month = models.IntegerField(
        default=26,
        validators=[MinValueValidator(1)],
        help_text="Working days per month"
    )
    
    # Team Assignment
    assigned_users = models.ManyToManyField(
        User, blank=True, related_name='init_assigned_projects',
        help_text="Users assigned to this project"
    )
    
    # ==========================================================================
    # Auto Calculated Fields (Read-only)
    # ==========================================================================
    
    # Revised Contract Value = Original Contract Value + Approved VO
    revised_contract_value = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal('0.00'),
        help_text="Auto-calculated: Original Contract Value + Approved VO"
    )
    
    # Delay Days = Forecast Finish - Contract Finish
    delay_days = models.IntegerField(
        default=0,
        help_text="Auto-calculated: Days between forecast and contract finish"
    )

    def save(self, *args, **kwargs):
        """
        Override save to auto-calculate derived fields:
        - revised_contract_value = original_contract_value + approved_vo
        - delay_days = (forecast_finish - contract_finish).days
        Only recalculate if relevant fields have changed.
        """
        # Check if this is a new project creation
        is_new = self.pk is None

        # Normalize string fields
        if self.name:
            self.name = self.name.strip()
        if self.client_name:
            self.client_name = self.client_name.strip()
        if self.location:
            self.location = self.location.strip()

        # Only recalculate if this is a new instance or relevant fields have changed
        if self.pk is None:
            # New instance, always calculate
            self._calculate_derived_fields()
        else:
            # Existing instance, check if calculation fields changed
            try:
                old_instance = Project.objects.get(pk=self.pk)
                if (old_instance.original_contract_value != self.original_contract_value or
                    old_instance.approved_vo != self.approved_vo or
                    old_instance.forecast_finish != self.forecast_finish or
                    old_instance.contract_finish != self.contract_finish):
                    self._calculate_derived_fields()
            except Project.DoesNotExist:
                # Fallback to always calculate if instance not found
                self._calculate_derived_fields()

        super().save(*args, **kwargs)

        # Send notification for new project creation
        if is_new:
            from services.notifications import notify_project_created
            notify_project_created(self)

    def _calculate_derived_fields(self):
        """Helper method to calculate derived fields"""
        # Calculate Revised Contract Value
        self.revised_contract_value = (
            (self.original_contract_value or ZERO) +
            (self.approved_vo or ZERO)
        )

        # Calculate Delay Days
        if self.forecast_finish and self.contract_finish:
            self.delay_days = (self.forecast_finish - self.contract_finish).days
        else:
            self.delay_days = 0

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Project"
        verbose_name_plural = "Projects"
        indexes = [
            models.Index(fields=["name", "status"], name="project_name_status_idx"),
            models.Index(fields=["status", "created_at"], name="project_status_created_idx"),
        ]

    def __str__(self):
        return self.name

class Site(models.Model):
    STATUS_CHOICES = [
        ('not_started', 'Not Started'),
        ('active', 'Active'),
        ('completed', 'Completed'),
    ]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='sites', db_index=True)
    name = models.CharField(max_length=255)
    location = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='not_started', db_index=True)
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

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Project Dashboard Data"
        verbose_name_plural = "Project Dashboard Data"
    
    def __str__(self):
        return f"Dashboard Data for {self.project.name}"

