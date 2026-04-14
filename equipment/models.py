"""
Project equipment: monthly planned vs actual counts with running cumulative totals.

Cumulative logic: for each project, rows ordered by calendar month; each row’s
planned_cumulative / actual_cumulative is the sum of monthly values from the
first month through that month (recomputed whenever a row is added).
"""

from django.db import models, transaction


class ProjectEquipment(models.Model):
    project_name = models.CharField(max_length=255, db_index=True)
    # First calendar day of the month (enforces ordering and uniqueness per project)
    month = models.DateField(db_index=True, help_text="First day of the month for this record")
    planned_equipment = models.PositiveIntegerField()
    actual_equipment = models.PositiveIntegerField()
    planned_cumulative = models.PositiveIntegerField(default=0)
    actual_cumulative = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["project_name", "month"]
        verbose_name = "Project equipment (monthly)"
        verbose_name_plural = "Project equipment records"
        indexes = [
            models.Index(fields=["project_name", "month"], name="equipment_project_month_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["project_name", "month"],
                name="equipment_unique_project_month",
            ),
        ]

    def save(self, *args, **kwargs):
        # Normalize project_name by stripping whitespace
        if self.project_name:
            self.project_name = self.project_name.strip()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.project_name} @ {self.month:%Y-%m}"

    @classmethod
    def recalculate_cumulatives(cls, project_name: str) -> None:
        """
        Running sums in month order for one project.
        planned_cumulative[n] = sum(planned_equipment[0..n])
        actual_cumulative[n] = sum(actual_equipment[0..n])
        """
        rows = cls.objects.filter(project_name=project_name).only(
            "id", "planned_equipment", "actual_equipment", "planned_cumulative", "actual_cumulative"
        ).order_by("month")

        with transaction.atomic():
            p_run = 0
            a_run = 0
            rows_to_update = []
            for row in rows:
                p_run += row.planned_equipment
                a_run += row.actual_equipment
                if row.planned_cumulative != p_run or row.actual_cumulative != a_run:
                    row.planned_cumulative = p_run
                    row.actual_cumulative = a_run
                    rows_to_update.append(row)

            if rows_to_update:
                cls.objects.bulk_update(rows_to_update, ["planned_cumulative", "actual_cumulative"])
