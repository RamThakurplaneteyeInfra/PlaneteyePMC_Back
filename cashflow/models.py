"""
Monthly cash-in / cash-out (plan & actual) plus actual cost, with running cumulative totals.

Cumulatives are recomputed in calendar order (year, month) whenever a row is added.
"""

from django.db import models


class CashFlow(models.Model):
    project_name = models.CharField(max_length=255, db_index=True)
    month_year = models.CharField(max_length=12, db_index=True)

    cash_in_monthly_plan = models.FloatField()
    cash_in_monthly_actual = models.FloatField()
    cash_out_monthly_plan = models.FloatField()
    cash_out_monthly_actual = models.FloatField()
    actual_cost_monthly = models.FloatField()

    cash_in_cumulative_plan = models.FloatField(default=0)
    cash_in_cumulative_actual = models.FloatField(default=0)
    cash_out_cumulative_plan = models.FloatField(default=0)
    cash_out_cumulative_actual = models.FloatField(default=0)
    actual_cost_cumulative = models.FloatField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["project_name", "month_year"]
        verbose_name = "Cash flow (monthly)"
        verbose_name_plural = "Cash flow records"
        constraints = [
            models.UniqueConstraint(
                fields=["project_name", "month_year"],
                name="cashflow_unique_project_month_year",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.project_name} — {self.month_year}"

    @classmethod
    def recalculate_cumulatives(cls, project_name: str) -> None:
        """Running sums over calendar-sorted rows for all five monthly series."""
        from datetime import datetime

        def _key(my: str) -> tuple[int, int]:
            dt = datetime.strptime(my.strip(), "%b-%Y")
            return (dt.year, dt.month)

        rows = list(cls.objects.filter(project_name=project_name))
        rows.sort(key=lambda r: _key(r.month_year))

        c_in_p = c_in_a = c_out_p = c_out_a = cost = 0.0
        for row in rows:
            c_in_p += row.cash_in_monthly_plan
            c_in_a += row.cash_in_monthly_actual
            c_out_p += row.cash_out_monthly_plan
            c_out_a += row.cash_out_monthly_actual
            cost += row.actual_cost_monthly

            cls.objects.filter(pk=row.pk).update(
                cash_in_cumulative_plan=round(c_in_p, 4),
                cash_in_cumulative_actual=round(c_in_a, 4),
                cash_out_cumulative_plan=round(c_out_p, 4),
                cash_out_cumulative_actual=round(c_out_a, 4),
                actual_cost_cumulative=round(cost, 4),
            )
