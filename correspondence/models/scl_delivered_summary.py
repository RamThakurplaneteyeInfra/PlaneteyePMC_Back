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
    # Legacy delivered-only counters retained for older rows/clients.
    client = models.PositiveIntegerField(default=0)
    contractor = models.PositiveIntegerField(default=0)
    other_agency = models.PositiveIntegerField(default=0)

    client_received = models.PositiveIntegerField(default=0)
    client_delivered = models.PositiveIntegerField(default=0)
    contractor_received = models.PositiveIntegerField(default=0)
    contractor_delivered = models.PositiveIntegerField(default=0)
    other_agency_received = models.PositiveIntegerField(default=0)
    other_agency_delivered = models.PositiveIntegerField(default=0)

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
        return self.total_delivered

    @staticmethod
    def pending(received: int | None, delivered: int | None) -> int:
        return max(int(received or 0) - int(delivered or 0), 0)

    @property
    def client_pending(self) -> int:
        return self.pending(self.client_received, self.client_delivered)

    @property
    def contractor_pending(self) -> int:
        return self.pending(self.contractor_received, self.contractor_delivered)

    @property
    def other_agency_pending(self) -> int:
        return self.pending(self.other_agency_received, self.other_agency_delivered)

    @property
    def total_received(self) -> int:
        return (
            self.client_received
            + self.contractor_received
            + self.other_agency_received
        )

    @property
    def total_delivered(self) -> int:
        return (
            self.client_delivered
            + self.contractor_delivered
            + self.other_agency_delivered
        )

    @property
    def total_pending(self) -> int:
        return (
            self.client_pending
            + self.contractor_pending
            + self.other_agency_pending
        )

    def to_api_dict(self) -> dict:
        return {
            "client": {
                "received": self.client_received,
                "delivered": self.client_delivered,
                "pending": self.client_pending,
            },
            "contractor": {
                "received": self.contractor_received,
                "delivered": self.contractor_delivered,
                "pending": self.contractor_pending,
            },
            "other_agency": {
                "received": self.other_agency_received,
                "delivered": self.other_agency_delivered,
                "pending": self.other_agency_pending,
            },
            "totals": {
                "received": self.total_received,
                "delivered": self.total_delivered,
                "pending": self.total_pending,
            },
            # Legacy aliases for delivered-only consumers.
            "client_delivered": self.client_delivered,
            "contractor_delivered": self.contractor_delivered,
            "other_agency_delivered": self.other_agency_delivered,
            "total": self.total_delivered,
        }

    def __str__(self):
        return (
            f"SCL Delivered — {self.project_name} "
            f"{self.month:02d}/{self.year} ({self.view})"
        )
