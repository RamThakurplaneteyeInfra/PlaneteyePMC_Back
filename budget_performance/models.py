"""
Budget vs Cost Performance — Earned Value Management (EVM) stored metrics.

Inputs map to: BAC (budget at completion), BCWP (earned value), ACWP (actual cost).
"""

from django.db import models

from projects.models import Project


class BudgetCostPerformance(models.Model):
    """
    One snapshot of budget vs cost performance for a project.

    - BAC: Budget at Completion
    - BCWP: Budgeted Cost of Work Performed (Earned Value)
    - ACWP: Actual Cost of Work Performed
    """

    project_name = models.CharField(max_length=255, db_index=True)  # Keep for transition
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='budget_performances'
    )

    bac = models.DecimalField(
        max_digits=24,
        decimal_places=4,
        help_text="Budget at Completion (BAC)",
    )
    bcwp = models.DecimalField(
        max_digits=24,
        decimal_places=4,
        help_text="Earned Value / BCWP",
    )
    acwp = models.DecimalField(
        max_digits=24,
        decimal_places=4,
        help_text="Actual Cost / ACWP",
    )

    # Derived EVM metrics (computed on create)
    cpi = models.DecimalField(
        max_digits=24,
        decimal_places=6,
        help_text="Cost Performance Index = BCWP / ACWP",
    )
    eac = models.DecimalField(
        max_digits=24,
        decimal_places=4,
        help_text="Estimate at Completion = BAC / CPI",
    )
    etg = models.DecimalField(
        max_digits=24,
        decimal_places=4,
        help_text="Estimate to Go = EAC - ACWP",
    )
    vac = models.DecimalField(
        max_digits=24,
        decimal_places=4,
        help_text="Variance at Completion = BAC - EAC",
    )
    cv = models.DecimalField(
        max_digits=24,
        decimal_places=4,
        help_text="Cost Variance = BCWP - ACWP",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Budget Cost Performance"
        verbose_name_plural = "Budget Cost Performance Records"

    def __str__(self) -> str:
        return f"{self.project_name} @ {self.created_at:%Y-%m-%d %H:%M}"
