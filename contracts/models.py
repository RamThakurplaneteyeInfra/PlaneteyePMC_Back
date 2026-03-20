from django.db import models
from django.core.validators import MinValueValidator


class Contract(models.Model):
    """
    Contract Management Workflow

    Workflow:
    - Billing Site Engineer creates contract -> status becomes PENDING
    - CEO approves -> status APPROVED + calculations are frozen into DB fields
    - CEO rejects -> status REJECTED
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    project_name = models.CharField(max_length=255)

    # Use Decimal for money to avoid float rounding issues
    original_contract_value = models.DecimalField(max_digits=18, decimal_places=2)
    approved_vo = models.DecimalField(
        max_digits=18, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )
    pending_vo = models.DecimalField(
        max_digits=18, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )

    # Calculated fields (stored after CEO approval)
    revised_contract_value = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    # Percentage is better represented as float
    approved_vo_percentage = models.FloatField(default=0.0, validators=[MinValueValidator(0.0)])

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)

    # Simple string fields as requested (can be replaced with FK to User later)
    created_by = models.CharField(max_length=255)
    approved_by = models.CharField(max_length=255, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["project_name", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.project_name} ({self.status})"
