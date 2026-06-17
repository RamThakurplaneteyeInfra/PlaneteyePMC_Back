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


class ProjectBGStatus(models.Model):
    """
    Bank Guarantee (BG) Status — optional dates per project.

    One record per project. Both dates are optional.
    """

    project = models.OneToOneField(
        Project,
        on_delete=models.CASCADE,
        related_name="bg_status_record",
        help_text="Project this BG status belongs to",
    )
    contractor_bg_date = models.DateField(
        null=True,
        blank=True,
        help_text="Contractor bank guarantee date (optional)",
    )
    scl_bg_date = models.DateField(
        null=True,
        blank=True,
        help_text="SCL bank guarantee date (optional)",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Project BG Status"
        verbose_name_plural = "Project BG Status Records"

    def __str__(self) -> str:
        project_name = self.project.name if self.project_id else "Unknown"
        return f"{project_name} — BG Status"
