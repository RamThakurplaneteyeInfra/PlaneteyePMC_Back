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


class ProjectCostPerformance(models.Model):
    project_name = models.CharField(max_length=255, db_index=True)
    month_year = models.CharField(max_length=12, db_index=True)

    bcws = models.FloatField(help_text="Budgeted Cost of Work Scheduled (planned cost)")
    bcwp = models.FloatField(help_text="Budgeted Cost of Work Performed (earned value)")
    acwp = models.FloatField(help_text="Actual Cost of Work Performed")
    fcst = models.FloatField(help_text="Forecast cost of remaining work")

    eac = models.FloatField(default=0, help_text="EAC = ACWP + FCST")
    cv = models.FloatField(default=0, help_text="CV = BCWP - ACWP")
    sv = models.FloatField(default=0, help_text="SV = BCWP - BCWS")

    # Optional enhancements (nullable)
    bac = models.FloatField(
        null=True,
        blank=True,
        help_text="Budget at completion (optional; used for VAC)",
    )
    cpi = models.FloatField(null=True, blank=True, help_text="CPI = BCWP/ACWP")
    vac = models.FloatField(null=True, blank=True, help_text="VAC = BAC - EAC when BAC set")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["project_name", "month_year"]
        verbose_name = "Project cost performance"
        verbose_name_plural = "Project cost performance records"
        constraints = [
            models.UniqueConstraint(
                fields=["project_name", "month_year"],
                name="costperf_unique_project_month_year",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.project_name} — {self.month_year}"

    def save(self, *args, **kwargs):
        """
        Calculate EVM metrics every time the object is saved.
        
        Formulas:
            EAC = ACWP + FCST           (estimate at completion)
            CV  = BCWP - ACWP           (cost variance)
            SV  = BCWP - BCWS           (schedule variance)
            CPI = BCWP / ACWP           (cost performance index, if ACWP > 0)
            VAC = BAC - EAC             (variance at completion, if BAC provided)
        """
        # EAC = ACWP + FCST
        self.eac = round(self.acwp + self.fcst, 4)
        
        # CV = BCWP - ACWP
        self.cv = round(self.bcwp - self.acwp, 4)
        
        # SV = BCWP - BCWS
        self.sv = round(self.bcwp - self.bcws, 4)
        
        # CPI = BCWP / ACWP (handle division by zero)
        if self.acwp > 0:
            self.cpi = round(self.bcwp / self.acwp, 6)
        else:
            self.cpi = None
        
        # VAC = BAC - EAC (only if BAC is provided)
        if self.bac is not None:
            self.vac = round(float(self.bac) - self.eac, 4)
        else:
            self.vac = None
        
        super().save(*args, **kwargs)
