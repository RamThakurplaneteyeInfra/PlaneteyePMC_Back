"""Stored SCL delivered correspondence counts (entered via dashboard modal)."""

from django.db import models
from django.utils import timezone


class SCLDeliveredCorrespondenceSummary(models.Model):
    """
    Manual SCL delivered counts per project / period / view.

    One row per (project_name, year, month, view).
    """

    VIEW_MONTHLY = "monthly"
    VIEW_CUMULATIVE = "cumulative"

    VIEW_CHOICES = [
        (VIEW_MONTHLY, "Monthly"),
        (VIEW_CUMULATIVE, "Cumulative"),
    ]

    project_name = models.CharField(max_length=255, db_index=True)
    month = models.PositiveSmallIntegerField(db_index=True)
    year = models.PositiveSmallIntegerField(db_index=True)
    view = models.CharField(
        max_length=20,
        choices=VIEW_CHOICES,
        default=VIEW_MONTHLY,
        db_index=True,
    )
    client = models.PositiveIntegerField(default=0)
    contractor = models.PositiveIntegerField(default=0)
    other_agency = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-year", "-month", "project_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["project_name", "year", "month", "view"],
                name="scl_delivered_unique_project_period_view",
            )
        ]
        verbose_name = "SCL Delivered Correspondence Summary"
        verbose_name_plural = "SCL Delivered Correspondence Summaries"

    @property
    def total(self) -> int:
        return self.client + self.contractor + self.other_agency

    def to_api_dict(self) -> dict:
        return {
            "client": self.client,
            "contractor": self.contractor,
            "other_agency": self.other_agency,
            "total": self.total,
        }

    def __str__(self):
        return (
            f"SCL Delivered — {self.project_name} "
            f"{self.month:02d}/{self.year} ({self.view})"
        )
