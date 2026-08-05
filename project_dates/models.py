"""
Project Dates Model.

Stores project schedule information separately for SCL and Contractor
within a single table, linked to the Project model via ForeignKey.

Each project can have:
  - Exactly one SCL schedule (contractor_name is null)
  - One or more CONTRACTOR schedules (each identified by contractor_name)

Calculated fields (not stored — computed in the serializer):
  - elapsed_duration       = (today - project_start).days
  - remaining_duration     = (contract_finish - today).days
  - forecast_finish_duration = (forecast_finish - contract_finish).days
  - eot_duration           = (eot_date - contract_finish).days

Business rules enforced in clean():
  - project_start   <= contract_finish
  - contract_finish <= eot_date (when eot_date is set)
  - contractor_name required when date_type = CONTRACTOR
  - contractor_name must be null/blank when date_type = SCL
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from projects.models import Project


class ProjectDates(models.Model):
    """
    Project schedule dates for SCL or a named Contractor.

    SCL: one row per project (contractor_name is null).
    CONTRACTOR: many rows per project, unique by contractor_name.
    """

    DATE_TYPE_SCL = "SCL"
    DATE_TYPE_CONTRACTOR = "CONTRACTOR"

    DATE_TYPE_CHOICES = [
        (DATE_TYPE_SCL, "SCL"),
        (DATE_TYPE_CONTRACTOR, "CONTRACTOR"),
    ]

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="project_dates",
        db_index=True,
        help_text="Project this date record belongs to",
    )
    date_type = models.CharField(
        max_length=20,
        choices=DATE_TYPE_CHOICES,
        db_index=True,
        help_text="SCL or CONTRACTOR",
    )
    contractor_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        db_index=True,
        help_text="Contractor display name (denormalized from Contractor Master)",
    )
    contractor = models.ForeignKey(
        "contractors.Contractor",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="project_dates",
        db_index=True,
        help_text="Contractor Master reference (required for CONTRACTOR)",
    )

    project_start = models.DateField(help_text="Project start date")
    contract_finish = models.DateField(help_text="Contractual finish date")
    forecast_finish = models.DateField(help_text="Forecasted finish date")
    eot_date = models.DateField(
        null=True,
        blank=True,
        help_text="Extension of Time (EOT) date (optional)",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="Record creation timestamp",
    )
    updated_at = models.DateTimeField(auto_now=True, help_text="Last update timestamp")

    def clean(self):
        errors = {}

        if self.date_type == self.DATE_TYPE_SCL:
            if self.contractor_name and str(self.contractor_name).strip():
                errors["contractor_name"] = (
                    "contractor_name must be empty for SCL records."
                )
            if self.contractor_id:
                errors["contractor_id"] = "contractor must be empty for SCL records."
        elif self.date_type == self.DATE_TYPE_CONTRACTOR:
            if not self.contractor_id and not (self.contractor_name or "").strip():
                errors["contractor_id"] = (
                    "contractor_id is required for CONTRACTOR records."
                )

        if self.project_start and self.contract_finish:
            if self.project_start > self.contract_finish:
                errors["project_start"] = (
                    "project_start must be on or before contract_finish. "
                    f"Got project_start={self.project_start}, "
                    f"contract_finish={self.contract_finish}."
                )

        if self.contract_finish and self.eot_date:
            if self.contract_finish > self.eot_date:
                errors["eot_date"] = (
                    "eot_date must be on or after contract_finish. "
                    f"Got contract_finish={self.contract_finish}, "
                    f"eot_date={self.eot_date}."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.date_type == self.DATE_TYPE_SCL:
            self.contractor_name = None
            self.contractor = None
        elif self.contractor_id:
            self.contractor_name = self.contractor.contractor_name
        elif self.contractor_name:
            self.contractor_name = str(self.contractor_name).strip()
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        project_name = self.project.name if self.project_id else "Unknown"
        if self.date_type == self.DATE_TYPE_CONTRACTOR and self.contractor_name:
            label = f"{self.contractor_name} [{self.date_type}]"
        else:
            label = self.date_type
        return (
            f"{project_name} — {label} — "
            f"Start: {self.project_start} | "
            f"Contract: {self.contract_finish} | "
            f"Forecast: {self.forecast_finish} | "
            f"EOT: {self.eot_date}"
        )

    class Meta:
        ordering = ["project__name", "date_type", "contractor_name"]
        verbose_name = "Project Dates"
        verbose_name_plural = "Project Dates"
        constraints = [
            models.UniqueConstraint(
                fields=["project", "date_type"],
                condition=Q(date_type="SCL"),
                name="pd_unique_scl_per_project",
            ),
            models.UniqueConstraint(
                fields=["project", "contractor"],
                condition=Q(date_type="CONTRACTOR"),
                name="pd_unique_contractor_per_project",
            ),
        ]
        indexes = [
            models.Index(
                fields=["project", "date_type"],
                name="pd_project_date_type_idx",
            ),
            models.Index(
                fields=["date_type"],
                name="pd_date_type_idx",
            ),
            models.Index(
                fields=["project", "contractor_name"],
                name="pd_project_contractor_idx",
            ),
        ]


class BGStatus(models.Model):
    """
    Bank Guarantee (BG) entry — multiple records per ProjectDates row.

    Status is never stored; it is calculated dynamically from due_date and updated_date.
    """

    BG_TYPE_CONTRACTOR = "CONTRACTOR"
    BG_TYPE_SCL = "SCL"

    BG_TYPE_CHOICES = [
        (BG_TYPE_CONTRACTOR, "Contractor"),
        (BG_TYPE_SCL, "SCL"),
    ]

    project_date = models.ForeignKey(
        ProjectDates,
        on_delete=models.CASCADE,
        related_name="bg_statuses",
        db_index=True,
        help_text="Parent project dates record (SCL or CONTRACTOR)",
    )
    bg_type = models.CharField(
        max_length=20,
        choices=BG_TYPE_CHOICES,
        db_index=True,
        help_text="Contract type for this bank guarantee",
    )
    bg_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Display name for this bank guarantee (optional)",
    )
    due_date = models.DateField(
        null=True,
        blank=True,
        help_text="Bank guarantee due date (optional)",
    )
    updated_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date the bank guarantee was last updated",
    )
    remarks = models.TextField(blank=True, help_text="Optional notes")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]
        verbose_name = "BG Status"
        verbose_name_plural = "BG Status Entries"
        indexes = [
            models.Index(
                fields=["project_date", "bg_type"],
                name="pd_bg_project_date_type_idx",
            ),
        ]

    def __str__(self) -> str:
        project_name = (
            self.project_date.project.name
            if self.project_date_id and self.project_date.project_id
            else "Unknown"
        )
        return f"{project_name} — {self.bg_name} [{self.bg_type}]"


class ProjectBGStatus(models.Model):
    """
    DEPRECATED — legacy single BG record per project.

    Replaced by :model:`BGStatus` (many rows per project via ProjectDates).
    Retained for backward compatibility; do not use for new writes.
    """

    project = models.OneToOneField(
        Project,
        on_delete=models.CASCADE,
        related_name="bg_status_record",
        help_text="Project this BG status belongs to",
    )
    contractor_bg_due_date = models.DateField(
        null=True,
        blank=True,
        help_text="Contractor bank guarantee due date for the current monthly milestone",
    )
    contractor_bg_updated_date = models.DateField(
        null=True,
        blank=True,
        help_text="Contractor bank guarantee updated date",
    )
    scl_bg_due_date = models.DateField(
        null=True,
        blank=True,
        help_text="SCL bank guarantee due date for the current monthly milestone",
    )
    scl_bg_updated_date = models.DateField(
        null=True,
        blank=True,
        help_text="SCL bank guarantee updated date",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Project BG Status"
        verbose_name_plural = "Project BG Status Records"

    def __str__(self) -> str:
        project_name = self.project.name if self.project_id else "Unknown"
        return f"{project_name} — BG Status"


# Multi-EOT history (Project → many ProjectEOT)
from .eot_models import ProjectEOT  # noqa: E402,F401
