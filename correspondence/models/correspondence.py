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
    TYPE_OTHER_AGENCY = "OTHER_AGENCY"

    CORRESPONDENCE_TYPE_CHOICES = [
        (TYPE_CLIENT, "CLIENT"),
        (TYPE_CONTRACTOR, "CONTRACTOR"),
        (TYPE_OTHER_AGENCY, "OTHER_AGENCY"),
    ]

    RECIPIENT_CLIENT = "CLIENT"
    RECIPIENT_CONTRACTOR = "CONTRACTOR"
    RECIPIENT_OTHER_AGENCY = "OTHER_AGENCY"

    RECIPIENT_TYPE_CHOICES = [
        (RECIPIENT_CLIENT, "Client"),
        (RECIPIENT_CONTRACTOR, "Contractor"),
        (RECIPIENT_OTHER_AGENCY, "Other Agency"),
    ]

    FLOW_INBOUND = "INBOUND"
    FLOW_OUTBOUND_SCL = "OUTBOUND_SCL"

    FLOW_DIRECTION_CHOICES = [
        (FLOW_INBOUND, "Inbound"),
        (FLOW_OUTBOUND_SCL, "SCL Outbound"),
    ]

    SENDER_SCL = "SCL"
    SENDER_CLIENT = "CLIENT"
    SENDER_CONTRACTOR = "CONTRACTOR"

    SENDER_CHOICES = [
        (SENDER_SCL, "SCL"),
        (SENDER_CLIENT, "Client"),
        (SENDER_CONTRACTOR, "Contractor"),
    ]

    STATUS_PENDING = "PENDING"
    STATUS_DELIVERED_ON_TIME = "DELIVERED_ON_TIME"
    STATUS_DELIVERED_LATE = "DELIVERED_LATE"

    DELIVERED_STATUS_CHOICES = [
        (STATUS_PENDING, "PENDING"),
        (STATUS_DELIVERED_ON_TIME, "DELIVERED_ON_TIME"),
        (STATUS_DELIVERED_LATE, "DELIVERED_LATE"),
    ]

    CATEGORY_DELIVERY = "DELIVERY"
    CATEGORY_RECORD = "RECORD"

    CORRESPONDENCE_CATEGORY_CHOICES = [
        (CATEGORY_DELIVERY, "Delivery"),
        (CATEGORY_RECORD, "Record"),
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
    flow_direction = models.CharField(
        max_length=20,
        choices=FLOW_DIRECTION_CHOICES,
        default=FLOW_INBOUND,
        db_index=True,
        help_text="INBOUND = received tracking; OUTBOUND_SCL = sent by SCL",
    )
    sender = models.CharField(
        max_length=20,
        choices=SENDER_CHOICES,
        default=SENDER_CLIENT,
        db_index=True,
        help_text="Document sender (SCL for outbound correspondence)",
    )
    recipient_type = models.CharField(
        max_length=20,
        choices=RECIPIENT_TYPE_CHOICES,
        null=True,
        blank=True,
        db_index=True,
        help_text="Recipient for SCL outbound documents",
    )
    correspondence_category = models.CharField(
        max_length=20,
        choices=CORRESPONDENCE_CATEGORY_CHOICES,
        default=CATEGORY_DELIVERY,
        db_index=True,
        help_text="DELIVERY = normal delivery tracking; RECORD = filed as record",
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
        flow_direction: str | None = None,
    ) -> int:
        flow_direction = flow_direction or cls.FLOW_INBOUND
        agg = cls.objects.filter(
            project_name__iexact=(project_name or "").strip(),
            month=month,
            year=year,
            correspondence_type=correspondence_type,
            flow_direction=flow_direction,
        ).aggregate(max_sr=Max("sr_no"))
        return int(agg["max_sr"] or 0) + 1

    def clean(self):
        errors = {}

        if self.month is not None and not (1 <= self.month <= 12):
            errors["month"] = "month must be between 1 and 12."

        if self.year is not None and not (2000 <= self.year <= 2100):
            errors["year"] = "year must be between 2000 and 2100."

        allowed_types = {
            self.TYPE_CLIENT,
            self.TYPE_CONTRACTOR,
            self.TYPE_OTHER_AGENCY,
        }
        if self.correspondence_type and self.correspondence_type not in allowed_types:
            errors["correspondence_type"] = (
                "correspondence_type must be CLIENT, CONTRACTOR, or OTHER_AGENCY."
            )

        if self.flow_direction == self.FLOW_OUTBOUND_SCL:
            if self.sender != self.SENDER_SCL:
                errors["sender"] = "Outbound SCL documents must have sender SCL."
            if not self.recipient_type:
                errors["recipient_type"] = (
                    "recipient_type is required for SCL outbound documents."
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

        category = self.correspondence_category or self.CATEGORY_DELIVERY
        if category == self.CATEGORY_RECORD and self.delivered_date:
            errors["delivered_date"] = (
                "delivered_date is not allowed when correspondence_category is RECORD."
            )

        if errors:
            raise ValidationError(errors)

    def _apply_category_defaults(self):
        """Record documents are filed — not part of delivery tracking."""
        if self.correspondence_category == self.CATEGORY_RECORD:
            self.delivered_date = None

    def _apply_deadline_and_delivered_status(self):
        if self.received_date:
            self.deadline_date = self.received_date + timedelta(days=DEADLINE_DAYS)
        if not self.delivered_date:
            self.delivered_status = self.STATUS_PENDING
        elif self.deadline_date and self.delivered_date <= self.deadline_date:
            self.delivered_status = self.STATUS_DELIVERED_ON_TIME
        else:
            self.delivered_status = self.STATUS_DELIVERED_LATE

    def _apply_sender_defaults(self):
        """Derive sender/recipient defaults from flow for inbound records."""
        if self.flow_direction == self.FLOW_OUTBOUND_SCL:
            self.sender = self.SENDER_SCL
            if self.recipient_type and not self.correspondence_type:
                self.correspondence_type = self.recipient_type
            elif self.recipient_type:
                self.correspondence_type = self.recipient_type
            return
        self.sender = self.correspondence_type
        self.recipient_type = None
        if self.correspondence_type == self.TYPE_OTHER_AGENCY:
            self.correspondence_type = self.TYPE_CLIENT

    def save(self, *args, **kwargs):
        if self.project_name:
            self.project_name = self.project_name.strip()
        if not self.correspondence_category:
            self.correspondence_category = self.CATEGORY_DELIVERY
        self._apply_sender_defaults()
        self._apply_category_defaults()
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
                    "flow_direction",
                    "sr_no",
                ],
                name="corr_doc_unique_project_period_flow_sr",
            )
        ]
        indexes = [
            models.Index(
                fields=["project_name", "year", "month", "correspondence_type"],
                name="corr_doc_proj_period_type_idx",
            ),
            models.Index(fields=["year", "month"], name="corr_doc_year_month_idx"),
            # Metrics: project + inbound/outbound + period
            models.Index(
                fields=["project_name", "flow_direction", "year", "month"],
                name="corr_proj_flow_period_idx",
            ),
            # List/metrics: project + delivery status + category
            models.Index(
                fields=["project_name", "delivered_status", "correspondence_category"],
                name="corr_proj_status_cat_idx",
            ),
        ]


CorrespondenceStatus = CorrespondenceDocument
Correspondence = CorrespondenceDocument
