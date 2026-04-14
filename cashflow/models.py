"""
Monthly cash-in / cash-out (plan & actual) plus actual cost, with running cumulative totals.

Cumulatives are recomputed in calendar order (year, month) whenever a row is added.
"""

from django.db import models


class CashFlow(models.Model):
    project_name = models.CharField(max_length=255, db_index=True)
    month_year = models.CharField(max_length=12, db_index=True)

    cash_in_monthly_plan = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        help_text="Monthly planned cash inflow"
    )
    cash_in_monthly_actual = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        help_text="Monthly actual cash inflow"
    )
    cash_out_monthly_plan = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        help_text="Monthly planned cash outflow"
    )
    cash_out_monthly_actual = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        help_text="Monthly actual cash outflow"
    )
    actual_cost_monthly = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        help_text="Monthly actual cost"
    )

    cash_in_cumulative_plan = models.DecimalField(
        max_digits=14, decimal_places=4, default=0,
        help_text="Running total of planned cash inflow"
    )
    cash_in_cumulative_actual = models.DecimalField(
        max_digits=14, decimal_places=4, default=0,
        help_text="Running total of actual cash inflow"
    )
    cash_out_cumulative_plan = models.DecimalField(
        max_digits=14, decimal_places=4, default=0,
        help_text="Running total of planned cash outflow"
    )
    cash_out_cumulative_actual = models.DecimalField(
        max_digits=14, decimal_places=4, default=0,
        help_text="Running total of actual cash outflow"
    )
    actual_cost_cumulative = models.DecimalField(
        max_digits=14, decimal_places=4, default=0,
        help_text="Running total of actual cost"
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

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
        indexes = [
            models.Index(fields=["project_name", "month_year"], name="cashflow_project_month_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.project_name} — {self.month_year}"

    @classmethod
    def recalculate_cumulatives(cls, project_name: str) -> None:
        """
        Running sums over calendar-sorted rows for all five monthly series.

        Optimized version using bulk updates for performance while maintaining exact same sorting logic.
        """
        # Fetch only required fields for calculation and updates
        # Use database ordering by project_name first, then sort by month_year in Python
        # (since month_year format "Mon-YYYY" needs custom parsing for chronological order)
        queryset = cls.objects.filter(project_name=project_name).only(
            'id', 'month_year',
            'cash_in_monthly_plan', 'cash_in_monthly_actual',
            'cash_out_monthly_plan', 'cash_out_monthly_actual',
            'actual_cost_monthly'
        )

        # Sort chronologically using the same logic as the original implementation
        rows = sorted(list(queryset), key=cls._chronological_sort_key)

        if not rows:
            return

        # Calculate running totals (maintaining exact same logic as before)
        c_in_p = c_in_a = c_out_p = c_out_a = cost = cls._decimal_zero()
        updates = []

        for row in rows:
            # Add monthly values to running totals (exact same logic as original)
            c_in_p += row.cash_in_monthly_plan
            c_in_a += row.cash_in_monthly_actual
            c_out_p += row.cash_out_monthly_plan
            c_out_a += row.cash_out_monthly_actual
            cost += row.actual_cost_monthly

            # Prepare update data (maintaining exact rounding as original)
            updates.append(cls(
                pk=row.pk,
                cash_in_cumulative_plan=cls._round_decimal(c_in_p, 4),
                cash_in_cumulative_actual=cls._round_decimal(c_in_a, 4),
                cash_out_cumulative_plan=cls._round_decimal(c_out_p, 4),
                cash_out_cumulative_actual=cls._round_decimal(c_out_a, 4),
                actual_cost_cumulative=cls._round_decimal(cost, 4),
            ))

        # Bulk update for performance (single query instead of N queries)
        if updates:
            cls.objects.bulk_update(
                updates,
                ['cash_in_cumulative_plan', 'cash_in_cumulative_actual',
                 'cash_out_cumulative_plan', 'cash_out_cumulative_actual',
                 'actual_cost_cumulative']
            )

    @staticmethod
    def _chronological_sort_key(record):
        """Sort key for chronological ordering (same as original implementation)."""
        from datetime import datetime
        dt = datetime.strptime(record.month_year.strip(), "%b-%Y")
        return (dt.year, dt.month)

    @staticmethod
    def _decimal_zero():
        """Return Decimal zero for consistent typing."""
        from decimal import Decimal
        return Decimal('0')

    @staticmethod
    def _round_decimal(value, places):
        """Round decimal to specified places (maintaining original behavior)."""
        from decimal import Decimal, ROUND_HALF_UP
        return value.quantize(Decimal(f"0.{places * '0'}"), rounding=ROUND_HALF_UP)
