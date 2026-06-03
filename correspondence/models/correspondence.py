"""
Correspondence document tracking — monthly, project-wise, per CLIENT / CONTRACTOR.

Dashboard metrics are aggregated from documents at read time (not stored as counts).
"""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Max
from django.utils import timezone

DEADLINE_DAYS = 7


class CorrespondenceDocument(models.Model):
    """One correspondence document for a project month, year, and type."""

    TYPE_CLIENT = "CLIENT"
    TYPE_CONTRACTOR = "CONTRACTOR"

    CORRESPONDENCE_TYPE_CHOICES = [
        (TYPE_CLIENT, "CLIENT"),
        (TYPE_CONTRACTOR, "CONTRACTOR"),
    ]

    STATUS_PENDING = "PENDING"
    STATUS_DELIVERED_ON_TIME = "DELIVERED_ON_TIME"
    STATUS_DELIVERED_LATE = "DELIVERED_LATE"

    DELIVERED_STATUS_CHOICES = [
        (STATUS_PENDING, "PENDING"),
        (STATUS_DELIVERED_ON_TIME, "DELIVERED_ON_TIME"),
        (STATUS_DELIVERED_LATE, "DELIVERED_LATE"),
    ]

    project_name = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Project name",
    )
    month = models.PositiveSmallIntegerField(
        db_index=True,
        help_text="Month (1–12) this document belongs to",
    )
    year = models.PositiveSmallIntegerField(
        db_index=True,
        help_text="Year this document belongs to",
    )
    correspondence_type = models.CharField(
        max_length=20,
        choices=CORRESPONDENCE_TYPE_CHOICES,
        db_index=True,
        help_text="CLIENT or CONTRACTOR",
    )
    sr_no = models.PositiveIntegerField(
        help_text="Serial number within project, month, year, and type",
    )
    description = models.TextField(help_text="Document description")
    received_date = models.DateField(
        db_index=True,
        help_text="Date the document was received",
    )
    deadline_date = models.DateField(
        editable=False,
        help_text="Auto-calculated: received_date + 7 days",
    )
    delivered_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date delivered (null while pending)",
    )
    delivered_status = models.CharField(
        max_length=32,
        choices=DELIVERED_STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
        help_text="Auto-calculated: PENDING, DELIVERED_ON_TIME, DELIVERED_LATE",
    )

    created_at = models.DateTimeField(
        default=timezone.now,
        editable=False,
        db_index=True,
    )
    updated_at = models.DateTimeField(auto_now=True)

    # Legacy aliases
    PARTY_CLIENT = TYPE_CLIENT
    PARTY_CONTRACTOR = TYPE_CONTRACTOR
    PARTY_TYPE_CHOICES = CORRESPONDENCE_TYPE_CHOICES
    DELIVERY_STATUS_CHOICES = DELIVERED_STATUS_CHOICES

    @property
    def party_type(self) -> str:
        return self.correspondence_type

    @property
    def delivery_date(self):
        return self.delivered_date

    @property
    def delivery_status(self) -> str:
        return self.delivered_status

    @classmethod
    def next_sr_no(
        cls,
        project_name: str,
        month: int,
        year: int,
        correspondence_type: str,
    ) -> int:
        agg = cls.objects.filter(
            project_name__iexact=(project_name or "").strip(),
            month=month,
            year=year,
            correspondence_type=correspondence_type,
        ).aggregate(max_sr=Max("sr_no"))
        return int(agg["max_sr"] or 0) + 1

    def clean(self):
        errors = {}

        if self.month is not None and not (1 <= self.month <= 12):
            errors["month"] = "month must be between 1 and 12."

        if self.year is not None and not (2000 <= self.year <= 2100):
            errors["year"] = "year must be between 2000 and 2100."

        if self.correspondence_type and self.correspondence_type not in {
            self.TYPE_CLIENT,
            self.TYPE_CONTRACTOR,
        }:
            errors["correspondence_type"] = (
                "correspondence_type must be CLIENT or CONTRACTOR."
            )

        if self.sr_no is not None and self.sr_no < 1:
            errors["sr_no"] = "sr_no must be >= 1."

        if self.received_date and self.month and self.year:
            if (
                self.received_date.month != self.month
                or self.received_date.year != self.year
            ):
                errors["received_date"] = (
                    "received_date must fall within the selected month and year."
                )

        if (
            self.received_date
            and self.delivered_date
            and self.delivered_date < self.received_date
        ):
            errors["delivered_date"] = (
                "delivered_date cannot be before received_date."
            )

        if errors:
            raise ValidationError(errors)

    def _apply_deadline_and_delivered_status(self):
        if self.received_date:
            self.deadline_date = self.received_date + timedelta(days=DEADLINE_DAYS)
        if not self.delivered_date:
            self.delivered_status = self.STATUS_PENDING
        elif self.deadline_date and self.delivered_date <= self.deadline_date:
            self.delivered_status = self.STATUS_DELIVERED_ON_TIME
        else:
            self.delivered_status = self.STATUS_DELIVERED_LATE

    def save(self, *args, **kwargs):
        if self.project_name:
            self.project_name = self.project_name.strip()
        self._apply_deadline_and_delivered_status()
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return (
            f"{self.project_name} [{self.correspondence_type}] "
            f"{self.month:02d}/{self.year} #{self.sr_no} — {self.delivered_status}"
        )

    class Meta:
        ordering = [
            "project_name",
            "year",
            "month",
            "correspondence_type",
            "sr_no",
        ]
        verbose_name = "Correspondence Document"
        verbose_name_plural = "Correspondence Documents"
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "project_name",
                    "month",
                    "year",
                    "correspondence_type",
                    "sr_no",
                ],
                name="corr_doc_unique_project_period_type_sr",
            )
        ]
        indexes = [
            models.Index(fields=["project_name"], name="corr_doc_project_idx"),
            models.Index(
                fields=["project_name", "year", "month", "correspondence_type"],
                name="corr_doc_proj_period_type_idx",
            ),
            models.Index(fields=["year", "month"], name="corr_doc_year_month_idx"),
        ]


CorrespondenceStatus = CorrespondenceDocument
Correspondence = CorrespondenceDocument
