"""
Project cost performance (EVM-style) per month.

Formulas (this API):
  EAC = ACWP + FCST           (estimate at completion / forecast final cost)
  CV  = BCWP − ACWP           (cost variance; < 0 → over budget on cost)
  SV  = BCWP − BCWS           (schedule variance; < 0 → behind schedule)

Optional:
  CPI = BCWP / ACWP           (undefined if ACWP = 0)
  VAC = BAC − EAC             (when BAC supplied)
"""

from django.db import models

from projects.models import Project


class ProjectCostPerformance(models.Model):
    project_name = models.CharField(max_length=255, db_index=True)  # Keep for transition
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='cost_performances'
    )
    month_year = models.CharField(max_length=12, db_index=True)

    # Use DecimalField for financial precision (4 decimal places for calculations)
    bcws = models.DecimalField(
        max_digits=18, decimal_places=4,
        help_text="Budgeted Cost of Work Scheduled (planned cost)"
    )
    bcwp = models.DecimalField(
        max_digits=18, decimal_places=4,
        help_text="Budgeted Cost of Work Performed (earned value)"
    )
    acwp = models.DecimalField(
        max_digits=18, decimal_places=4,
        help_text="Actual Cost of Work Performed"
    )
    fcst = models.DecimalField(
        max_digits=18, decimal_places=4,
        help_text="Forecast cost of remaining work"
    )

    eac = models.DecimalField(
        max_digits=18, decimal_places=4, default=0,
        help_text="EAC = ACWP + FCST"
    )
    cv = models.DecimalField(
        max_digits=18, decimal_places=4, default=0,
        help_text="CV = BCWP - ACWP"
    )
    sv = models.DecimalField(
        max_digits=18, decimal_places=4, default=0,
        help_text="SV = BCWP - BCWS"
    )

    # Optional enhancements (nullable)
    bac = models.DecimalField(
        max_digits=18, decimal_places=4,
        null=True, blank=True,
        help_text="Budget at completion (optional; used for VAC)",
    )
    cpi = models.DecimalField(
        max_digits=10, decimal_places=6,
        null=True, blank=True,
        help_text="CPI = BCWP/ACWP"
    )
    vac = models.DecimalField(
        max_digits=18, decimal_places=4,
        null=True, blank=True,
        help_text="VAC = BAC - EAC when BAC set"
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["project__name", "month_year"]
        verbose_name = "Project cost performance"
        verbose_name_plural = "Project cost performance records"
        constraints = [
            models.UniqueConstraint(
                fields=["project", "month_year"],
                name="costperf_unique_project_month_year",
            ),
        ]
        indexes = [
            models.Index(fields=["project", "month_year"], name="costperf_project_month_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.project_name} — {self.month_year}"

    def save(self, *args, **kwargs):
        """
        Calculate EVM metrics with optimization to avoid unnecessary recalculations.

        Formulas (unchanged):
            EAC = ACWP + FCST           (estimate at completion)
            CV  = BCWP - ACWP           (cost variance)
            SV  = BCWP - BCWS           (schedule variance)
            CPI = BCWP / ACWP           (cost performance index, if ACWP > 0)
            VAC = BAC - EAC             (variance at completion, if BAC provided)
        """
        from decimal import Decimal

        # Check if base values have changed to avoid unnecessary calculations
        if self.pk:  # Existing instance
            old_instance = ProjectCostPerformance.objects.get(pk=self.pk)
            base_values_changed = (
                old_instance.bcws != self.bcws or
                old_instance.bcwp != self.bcwp or
                old_instance.acwp != self.acwp or
                old_instance.fcst != self.fcst or
                old_instance.bac != self.bac
            )
            if not base_values_changed:
                # Base values haven't changed, skip recalculation
                # Still sync project_name and normalize month_year
                if hasattr(self, 'project') and self.project:
                    self.project_name = self.project.name
                if self.month_year:
                    self.month_year = self.month_year.strip()
                super().save(*args, **kwargs)
                return

        # Normalize fields
        if hasattr(self, 'project') and self.project:
            self.project_name = self.project.name
        if self.month_year:
            self.month_year = self.month_year.strip()

        # Perform calculations in Decimal (exact same formulas, no float conversions)
        # EAC = ACWP + FCST
        self.eac = self.acwp + self.fcst

        # CV = BCWP - ACWP
        self.cv = self.bcwp - self.acwp

        # SV = BCWP - BCWS
        self.sv = self.bcwp - self.bcws

        # CPI = BCWP / ACWP (handle division by zero)
        if self.acwp != 0:
            self.cpi = self.bcwp / self.acwp
        else:
            self.cpi = None

        # VAC = BAC - EAC (only if BAC is provided)
        if self.bac is not None:
            self.vac = self.bac - self.eac
        else:
            self.vac = None

        super().save(*args, **kwargs)
