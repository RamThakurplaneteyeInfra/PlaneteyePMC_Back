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

    created_at = models.DateTimeField(auto_now_add=True)

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

        rows = list(cls.objects.filter(project_name=project_name))
        rows.sort(key=lambda r: _key(r.month_year))
        p_cum = 0.0
        a_cum = 0.0
        for row in rows:
            p_cum += row.planned_mh
            a_cum += row.actual_mh
            if (
                row.planned_mh_cumulative != p_cum
                or row.actual_mh_cumulative != a_cum
            ):
                cls.objects.filter(pk=row.pk).update(
                    planned_mh_cumulative=round(p_cum, 4),
                    actual_mh_cumulative=round(a_cum, 4),
                )
