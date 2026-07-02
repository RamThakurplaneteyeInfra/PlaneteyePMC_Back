"""Stored inbound (Client / Contractor) correspondence counts (dashboard modal)."""

from django.db import models
from django.utils import timezone


class InboundCorrespondenceSummary(models.Model):
    """
    Manual client and contractor correspondence counts per project / period / view.

    One row per (project_name, year, month, view).
    Pending is computed at read time: max(received - delivered - record, 0).
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

    client_received = models.PositiveIntegerField(default=0)
    client_delivered = models.PositiveIntegerField(default=0)
    client_record = models.PositiveIntegerField(default=0)
    contractor_received = models.PositiveIntegerField(default=0)
    contractor_delivered = models.PositiveIntegerField(default=0)
    contractor_record = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-year", "-month", "project_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["project_name", "year", "month", "view"],
                name="inbound_corr_unique_project_period_view",
            )
        ]
        verbose_name = "Inbound Correspondence Summary"
        verbose_name_plural = "Inbound Correspondence Summaries"

    @staticmethod
    def pending(received: int | None, delivered: int | None, record: int | None) -> int:
        return max(
            int(received or 0) - int(delivered or 0) - int(record or 0),
            0,
        )

    def client_metrics(self) -> dict:
        return {
            "received": self.client_received,
            "delivered": self.client_delivered,
            "record": self.client_record,
            "pending": self.pending(
                self.client_received,
                self.client_delivered,
                self.client_record,
            ),
        }

    def contractor_metrics(self) -> dict:
        return {
            "received": self.contractor_received,
            "delivered": self.contractor_delivered,
            "record": self.contractor_record,
            "pending": self.pending(
                self.contractor_received,
                self.contractor_delivered,
                self.contractor_record,
            ),
        }

    def __str__(self):
        return (
            f"Inbound Correspondence — {self.project_name} "
            f"{self.month:02d}/{self.year} ({self.view})"
        )
