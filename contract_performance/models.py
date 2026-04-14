from django.db import models
from django.core.validators import MinValueValidator


class ContractPerformance(models.Model):
    """
    Contract Performance Model
    
    Tracks contract performance metrics:
    - Earned Value: Value of work completed
    - Actual Billed: Amount actually billed
    - Variance: Difference between Earned Value and Actual Billed
    - Performance Status: Based on percentage thresholds (Red/Yellow/Green)
    
    Performance Thresholds:
    - Red: < 0.90 (< 90%)
    - Yellow: 0.90 - 0.99 (90% - 99%)
    - Green: >= 1.00 (>= 100%)
    
    Access Control:
    - Billing Site Engineer can view and edit
    """
    
    class PerformanceStatus(models.TextChoices):
        RED = "red", "Red (< 90%)"
        YELLOW = "yellow", "Yellow (90% - 99%)"
        GREEN = "green", "Green (>= 100%)"
    
    project_name = models.CharField(max_length=255, db_index=True, help_text="Project name for this performance record")
    
    # Base contract value for percentage calculations
    contract_value = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text="Base contract value for percentage calculations"
    )
    
    # Use Decimal for money to avoid float rounding issues
    earned_value = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Value of work completed (Earned Value)"
    )
    
    actual_billed = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Amount actually billed"
    )
    
    # Calculated fields
    earned_value_percentage = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        default=0,
        help_text="Earned Value percentage (calculated: earned_value / contract_value * 100)"
    )

    actual_billed_percentage = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        default=0,
        help_text="Actual Billed percentage (calculated: actual_billed / contract_value * 100)"
    )

    variance = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=0,
        help_text="Variance amount (calculated: earned_value - actual_billed). Can be negative if actual_billed > earned_value."
    )

    variance_percentage = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        default=0,
        help_text="Variance percentage (calculated: variance / contract_value * 100). Can be negative if actual_billed > earned_value."
    )
    
    performance_status = models.CharField(
        max_length=20,
        choices=PerformanceStatus.choices,
        default=PerformanceStatus.RED,
        help_text="Performance status based on earned_value_percentage thresholds"
    )
    
    # Tracking fields
    created_by = models.CharField(max_length=255, help_text="User who created this record")
    updated_by = models.CharField(max_length=255, null=True, blank=True, help_text="User who last updated this record")
    
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["project_name", "-created_at"]),
            models.Index(fields=["performance_status", "-created_at"]),
        ]
        verbose_name = "Contract Performance"
        verbose_name_plural = "Contract Performance"
    
    def __str__(self) -> str:
        return f"{self.project_name} - {self.performance_status.upper()} ({self.earned_value_percentage:.2f}%)"
    
    def save(self, *args, **kwargs):
        """
        Auto-calculate all derived fields before saving.
        Optimized to avoid unnecessary recalculations when base values haven't changed.
        """
        from decimal import Decimal, DivisionByZero

        # Check if base values have changed to avoid unnecessary calculations
        if self.pk:  # Existing instance
            old_instance = ContractPerformance.objects.get(pk=self.pk)
            base_values_changed = (
                old_instance.earned_value != self.earned_value or
                old_instance.actual_billed != self.actual_billed or
                old_instance.contract_value != self.contract_value
            )
            if not base_values_changed:
                # Base values haven't changed, skip recalculation
                super().save(*args, **kwargs)
                return

        # Normalize project_name to avoid duplicates
        if self.project_name:
            self.project_name = self.project_name.strip()

        try:
            # contract_value is already DecimalField, no need to wrap with Decimal()
            contract_val = self.contract_value

            # Calculate variance FIRST (can be negative if actual_billed > earned_value)
            self.variance = self.earned_value - self.actual_billed

            # Calculate percentages in Decimal, no float conversions
            if contract_val > 0:
                # Keep all calculations in Decimal for precision
                self.earned_value_percentage = (self.earned_value / contract_val) * Decimal("100")
                self.actual_billed_percentage = (self.actual_billed / contract_val) * Decimal("100")
                # Preserve negative sign: if variance is negative, variance_percentage will be negative
                self.variance_percentage = (self.variance / contract_val) * Decimal("100")
            else:
                self.earned_value_percentage = Decimal("0")
                self.actual_billed_percentage = Decimal("0")
                self.variance_percentage = Decimal("0")

            # Determine performance status based on earned_value_percentage
            # Convert to decimal for comparison (0.9592 for 95.92%)
            ev_percentage = self.earned_value_percentage / Decimal("100")

            if ev_percentage < Decimal("0.90"):
                self.performance_status = self.PerformanceStatus.RED
            elif Decimal("0.90") <= ev_percentage < Decimal("1.00"):
                self.performance_status = self.PerformanceStatus.YELLOW
            else:  # >= 1.00
                self.performance_status = self.PerformanceStatus.GREEN

        except DivisionByZero:
            # Handle division by zero specifically
            self.variance = self.earned_value - self.actual_billed
            self.earned_value_percentage = Decimal("0")
            self.actual_billed_percentage = Decimal("0")
            self.variance_percentage = Decimal("0")
            self.performance_status = self.PerformanceStatus.RED

        except Exception as e:
            # Re-raise unexpected exceptions instead of hiding them
            raise

        super().save(*args, **kwargs)
