"""
Project manpower: monthly headcount × hours × days → man-hours (MH) and running cumulative MH.

Cumulative order: calendar order from month_year (e.g. Jan-2023 → Feb-2023).
"""

from django.db import models


class ProjectManpower(models.Model):
    project_name = models.CharField(max_length=255, db_index=True)
    # Canonical format "Jan-2023" (%b-%Y)
    month_year = models.CharField(max_length=12, db_index=True)

    planned_manpower = models.PositiveIntegerField()
    actual_manpower = models.PositiveIntegerField()
    working_hours_per_day = models.FloatField()
    working_days_per_month = models.PositiveIntegerField()

    planned_mh = models.FloatField(default=0)
    actual_mh = models.FloatField(default=0)
    planned_mh_cumulative = models.FloatField(default=0)
    actual_mh_cumulative = models.FloatField(default=0)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["project_name", "month_year"]
        verbose_name = "Project manpower (monthly)"
        verbose_name_plural = "Project manpower records"
        constraints = [
            models.UniqueConstraint(
                fields=["project_name", "month_year"],
                name="manpower_unique_project_month_year",
            ),
        ]

    def save(self, *args, **kwargs):
        # Normalize project_name and month_year by stripping whitespace
        if self.project_name:
            self.project_name = self.project_name.strip()
        if self.month_year:
            self.month_year = self.month_year.strip()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.project_name} — {self.month_year}"

    @classmethod
    def recalculate_cumulatives(cls, project_name: str) -> None:
        """
        Sort rows by (year, month index) from month_year, then set running sums of planned_mh / actual_mh.
        """
        from datetime import datetime

        def _key(my: str) -> tuple[int, int]:
            dt = datetime.strptime(my.strip(), "%b-%Y")
            return (dt.year, dt.month)

        # Fetch only required fields to reduce memory usage
        rows = list(cls.objects.filter(project_name=project_name).only(
            "id", "month_year", "planned_mh", "actual_mh", "planned_mh_cumulative", "actual_mh_cumulative"
        ))
        rows.sort(key=lambda r: _key(r.month_year))
        p_cum = 0.0
        a_cum = 0.0
        rows_to_update = []
        for row in rows:
            p_cum += row.planned_mh
            a_cum += row.actual_mh
            if (
                row.planned_mh_cumulative != p_cum
                or row.actual_mh_cumulative != a_cum
            ):
                row.planned_mh_cumulative = round(p_cum, 4)
                row.actual_mh_cumulative = round(a_cum, 4)
                rows_to_update.append(row)

        # Use bulk_update for efficient batch updates
        if rows_to_update:
            cls.objects.bulk_update(rows_to_update, ["planned_mh_cumulative", "actual_mh_cumulative"])
