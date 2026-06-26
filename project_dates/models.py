"""
Project Dates Model.

Stores project schedule information separately for SCL and Contractor
within a single table, linked to the Project model via ForeignKey.

Each project can have exactly two records:
  - One for SCL
  - One for CONTRACTOR

Calculated fields (not stored — computed in the serializer):
  - elapsed_duration       = (today - project_start).days
  - remaining_duration     = (contract_finish - today).days
  - forecast_finish_duration = (forecast_finish - contract_finish).days
  - eot_duration           = (eot_date - contract_finish).days

Business rules enforced in clean():
  - project_start   <= contract_finish
  - contract_finish <= eot_date

  forecast_finish may be before or after contract_finish (early or delayed forecast).
  - One SCL record per project
  - One CONTRACTOR record per project
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from projects.models import Project


class ProjectDates(models.Model):
    """
    Project schedule dates for SCL or Contractor.

    One record per (project, date_type) pair.
    Calculated duration fields are derived at read time in the serializer —
    they are never stored in the database.
    """

    DATE_TYPE_SCL = "SCL"
    DATE_TYPE_CONTRACTOR = "CONTRACTOR"

    DATE_TYPE_CHOICES = [
        (DATE_TYPE_SCL, "SCL"),
        (DATE_TYPE_CONTRACTOR, "CONTRACTOR"),
    ]

    # -------------------------------------------------------------------------
    # Core identifiers
    # -------------------------------------------------------------------------
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

    # -------------------------------------------------------------------------
    # Date fields
    # -------------------------------------------------------------------------
    project_start = models.DateField(
        help_text="Project start date",
    )
    contract_finish = models.DateField(
        help_text="Contractual finish date",
    )
    forecast_finish = models.DateField(
        help_text="Forecasted finish date",
    )
    eot_date = models.DateField(
        help_text="Extension of Time (EOT) date",
    )

    # -------------------------------------------------------------------------
    # Timestamps
    # -------------------------------------------------------------------------
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="Record creation timestamp",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Last update timestamp",
    )

    # =========================================================================
    # Validation
    # =========================================================================

    def clean(self):
        """
        Business rule validation:
          1. project_start   <= contract_finish
          2. contract_finish <= eot_date

          forecast_finish is not constrained relative to contract_finish —
          it may be earlier (ahead of schedule) or later (delayed).
        """
        errors = {}

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
        """Run full validation before persisting."""
        self.full_clean()
        super().save(*args, **kwargs)

    # =========================================================================
    # Meta & helpers
    # =========================================================================

    def __str__(self) -> str:
        project_name = self.project.name if self.project_id else "Unknown"
        return (
            f"{project_name} [{self.date_type}] — "
            f"Start: {self.project_start} | "
            f"Contract: {self.contract_finish} | "
            f"Forecast: {self.forecast_finish} | "
            f"EOT: {self.eot_date}"
        )

    class Meta:
        ordering = ["project__name", "date_type"]
        verbose_name = "Project Dates"
        verbose_name_plural = "Project Dates"
        # One SCL record and one CONTRACTOR record per project
        unique_together = [("project", "date_type")]
        indexes = [
            models.Index(
                fields=["project", "date_type"],
                name="pd_project_date_type_idx",
            ),
            models.Index(
                fields=["date_type"],
                name="pd_date_type_idx",
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
        help_text="Contractor or SCL bank guarantee",
    )
    bg_name = models.CharField(
        max_length=255,
        help_text="Display name for this bank guarantee",
    )
    due_date = models.DateField(
        help_text="Bank guarantee due date",
    )
    updated_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date the bank guarantee was last updated",
    )
    remarks = models.TextField(
        blank=True,
        help_text="Optional notes",
    )
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
