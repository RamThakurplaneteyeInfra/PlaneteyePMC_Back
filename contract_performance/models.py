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
    
    project_name = models.CharField(max_length=255, help_text="Project name for this performance record")
    
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
    earned_value_percentage = models.FloatField(
        default=0.0,
        help_text="Earned Value percentage (calculated: earned_value / contract_value * 100)"
    )
    
    actual_billed_percentage = models.FloatField(
        default=0.0,
        help_text="Actual Billed percentage (calculated: actual_billed / contract_value * 100)"
    )
    
    variance = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=0,
        help_text="Variance amount (calculated: earned_value - actual_billed). Can be negative if actual_billed > earned_value."
    )
    
    variance_percentage = models.FloatField(
        default=0.0,
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
    
    created_at = models.DateTimeField(auto_now_add=True)
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
        """
        from decimal import Decimal, DivisionByZero
        
        try:
            contract_val = Decimal(self.contract_value)
            
            # Calculate variance FIRST (can be negative if actual_billed > earned_value)
            self.variance = self.earned_value - self.actual_billed
            
            # Calculate percentages (variance_percentage will be negative if variance is negative)
            # Negative values are preserved and displayed as negative (not converted to positive)
            if contract_val > 0:
                self.earned_value_percentage = float((self.earned_value / contract_val) * Decimal("100"))
                self.actual_billed_percentage = float((self.actual_billed / contract_val) * Decimal("100"))
                # This preserves negative sign: if variance is negative, variance_percentage will be negative
                self.variance_percentage = float((self.variance / contract_val) * Decimal("100"))
            else:
                self.earned_value_percentage = 0.0
                self.actual_billed_percentage = 0.0
                self.variance_percentage = 0.0
            
            # Determine performance status based on earned_value_percentage
            ev_percentage = self.earned_value_percentage / 100.0  # Convert to decimal (0.9592 for 95.92%)
            
            if ev_percentage < 0.90:
                self.performance_status = self.PerformanceStatus.RED
            elif 0.90 <= ev_percentage < 1.00:
                self.performance_status = self.PerformanceStatus.YELLOW
            else:  # >= 1.00
                self.performance_status = self.PerformanceStatus.GREEN
                
        except (DivisionByZero, Exception):
            # Handle edge cases
            # Calculate variance first (can be negative)
            self.variance = self.earned_value - self.actual_billed
            # If contract_value is 0 or invalid, set percentages to 0, but preserve negative variance
            self.earned_value_percentage = 0.0
            self.actual_billed_percentage = 0.0
            # Preserve negative variance_percentage if variance is negative
            if self.contract_value > 0:
                self.variance_percentage = float((self.variance / Decimal(self.contract_value)) * Decimal("100"))
            else:
                self.variance_percentage = 0.0
            self.performance_status = self.PerformanceStatus.RED
        
        super().save(*args, **kwargs)
