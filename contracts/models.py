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

    project_name = models.CharField(max_length=255, db_index=True)

    # Use Decimal for money to avoid float rounding issues
    original_contract_value = models.DecimalField(
        max_digits=18, decimal_places=2, validators=[MinValueValidator(0)]
    )
    approved_vo = models.DecimalField(
        max_digits=18, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )
    pending_vo = models.DecimalField(
        max_digits=18, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )

    # Calculated fields (stored after CEO approval)
    revised_contract_value = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    # Use DecimalField for percentage to maintain precision
    approved_vo_percentage = models.DecimalField(
        max_digits=10, decimal_places=4, default=0, validators=[MinValueValidator(0)]
    )

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)

    # Simple string fields as requested (can be replaced with FK to User later)
    created_by = models.CharField(max_length=255)
    approved_by = models.CharField(max_length=255, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["project_name", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
        ]

    def save(self, *args, **kwargs):
        """
        Override save to normalize project_name and optimize updates.
        """
        # Normalize project_name to avoid duplicates due to whitespace
        if self.project_name:
            self.project_name = self.project_name.strip()

        # Only set status to PENDING for new contracts (not updates)
        if not self.pk and not self.status:
            self.status = self.Status.PENDING

        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.project_name} ({self.status})"
