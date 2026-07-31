from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from projects.models import Project


class ScopeCategory(models.Model):
    """
    Categories for Monthly Scope of Work
    """
    name = models.CharField(max_length=255, unique=True, help_text="Category name")
    display_order = models.PositiveIntegerField(default=0, help_text="Display order")
    is_active = models.BooleanField(default=True, help_text="Whether this category is active")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', 'name']
        verbose_name = "Scope Category"
        verbose_name_plural = "Scope Categories"

    def __str__(self):
        return self.name


class ScopeSubCategory(models.Model):
    """
    Subcategories for Monthly Scope of Work
    """
    category = models.ForeignKey(
        ScopeCategory,
        on_delete=models.CASCADE,
        related_name='subcategories',
        help_text="Parent category"
    )
    name = models.CharField(max_length=255, help_text="Subcategory name")
    display_order = models.PositiveIntegerField(default=0, help_text="Display order")
    is_active = models.BooleanField(default=True, help_text="Whether this subcategory is active")

    # Default quantity for this subcategory (optional)
    default_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Default quantity for this subcategory"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['category', 'display_order', 'name']
        verbose_name = "Scope Subcategory"
        verbose_name_plural = "Scope Subcategories"
        unique_together = [['category', 'name']]

    def __str__(self):
        return f"{self.category.name} - {self.name}"


class MonthlyScopeWork(models.Model):
    """
    Monthly Scope of Work model
    """

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
    ]

    # Relationships
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='monthly_scopes',
        help_text="Project this scope belongs to"
    )

    category = models.ForeignKey(
        ScopeCategory,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='scopes',
        help_text="Scope category"
    )

    subcategory = models.ForeignKey(
        ScopeSubCategory,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='scopes',
        help_text="Scope subcategory"
    )

    # Scope details
    month = models.DateField(null=True, blank=True, help_text="Month for this scope (first day of the month)")
    description = models.TextField(blank=True, help_text="Description of the scope")
    unit = models.CharField(max_length=50, blank=True, help_text="Unit of measurement (e.g., m3, nos, km)")
    planned_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Planned quantity"
    )

    # Location details
    section = models.CharField(max_length=255, blank=True, help_text="Section name")
    location = models.CharField(max_length=255, blank=True, help_text="Location details")

    # Dates
    start_date = models.DateField(null=True, blank=True, help_text="Planned start date")
    end_date = models.DateField(null=True, blank=True, help_text="Planned end date")

    # Custom names for "Other" options
    custom_category_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Custom category name when 'Other' is selected"
    )
    custom_subcategory_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Custom subcategory name when 'Other' is selected"
    )

    # Progress Tracking Fields (auto-calculated)
    cumulative_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0.00,
        help_text="Cumulative executed quantity from all DPRs"
    )

    remaining_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0.00,
        help_text="Remaining quantity to complete the scope"
    )

    progress_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.00,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Progress percentage (0-100)"
    )

    # Status
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        help_text="Current status of the scope"
    )

    # Audit fields
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_scopes',
        help_text="User who created this scope"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='updated_scopes',
        help_text="User who last updated this scope"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['project', 'month', 'category', 'subcategory']
        verbose_name = "Monthly Scope of Work"
        verbose_name_plural = "Monthly Scopes of Work"
        indexes = [
            models.Index(fields=['project', 'month']),
            models.Index(fields=['category', 'subcategory']),
            models.Index(fields=['status']),
        ]

    def save(self, *args, **kwargs):
        # Ensure month is first day of the month if provided
        if self.month:
            self.month = self.month.replace(day=1)
        super().save(*args, **kwargs)

    def __str__(self):
        month_str = self.month.strftime("%b-%Y") if self.month else "No Month"
        project_name = self.project.name if self.project_id else "No Project"
        category_name = self.category.name if self.category_id else "No Category"
        subcategory_name = self.subcategory.name if self.subcategory_id else "No Subcategory"
        return f"{project_name} - {month_str} - {category_name} - {subcategory_name}"

    def get_category_display_name(self):
        """Get display name for category (custom if Other)"""
        if not self.category_id:
            return ""
        if self.category.name == "Other":
            return self.custom_category_name or "Other"
        return self.category.name

    def get_subcategory_display_name(self):
        """Get display name for subcategory (custom if Other)"""
        if not self.subcategory_id:
            return ""
        if self.subcategory.name == "Other":
            return self.custom_subcategory_name or "Other"
        return self.subcategory.name


class ScopeAssignment(models.Model):
    """
    Assignment of Monthly Scope to Site Engineers
    """

    scope = models.ForeignKey(
        MonthlyScopeWork,
        on_delete=models.CASCADE,
        related_name='assignments',
        help_text="Scope being assigned"
    )

    site_engineer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='assigned_scopes',
        help_text="Site Engineer assigned to this scope"
    )

    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='scope_assignments_made',
        help_text="User who made this assignment"
    )

    assigned_at = models.DateTimeField(auto_now_add=True, help_text="When the assignment was made")

    class Meta:
        ordering = ['-assigned_at']
        verbose_name = "Scope Assignment"
        verbose_name_plural = "Scope Assignments"
        unique_together = [['scope', 'site_engineer']]
        indexes = [
            # Reverse lookup: filter(assignments__site_engineer=user)
            models.Index(fields=["site_engineer", "scope"], name="scope_asgn_se_scope_idx"),
        ]

    def __str__(self):
        return f"{self.scope} -> {self.site_engineer.get_full_name() or self.site_engineer.username}"