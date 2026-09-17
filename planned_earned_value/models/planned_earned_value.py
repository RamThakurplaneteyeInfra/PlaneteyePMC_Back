"""
Planned vs Actual — monthly project-wise financial tracking.

Supports:
  - One SCL record per (project, month, year)
  - Multiple CONTRACTOR records per (project, contractor, month, year)

Auto-calculated on save:
  difference              = planned_value - actual_value
  achievement_percentage  = (actual_value / planned_value) * 100
  collection_percentage   = (collection / actual_value) * 100
  variance_percentage     = (difference / planned_value) * 100
  variance_status         = ON_TRACK | MINOR_VARIANCE | MAJOR_VARIANCE
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from projects.models import Project

TWO_PLACES = Decimal("0.01")
ZERO = Decimal("0")


def _as_decimal(value) -> Decimal:
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _pct(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator == 0:
        return ZERO
    return ((numerator / denominator) * Decimal("100")).quantize(
        TWO_PLACES, rounding=ROUND_HALF_UP
    )


def compute_variance_status(difference: Decimal, planned_value: Decimal) -> str:
    if difference == 0:
        return PlannedEarnedValue.STATUS_ON_TRACK
    threshold = _as_decimal(planned_value) * Decimal("0.10")
    if difference <= threshold:
        return PlannedEarnedValue.STATUS_MINOR_VARIANCE
    return PlannedEarnedValue.STATUS_MAJOR_VARIANCE


class PlannedEarnedValue(models.Model):
    """Monthly Planned vs Actual record (SCL or CONTRACTOR)."""

    TYPE_SCL = "SCL"
    TYPE_CONTRACTOR = "CONTRACTOR"
    PLANNED_TYPE_CHOICES = [
        (TYPE_SCL, "SCL"),
        (TYPE_CONTRACTOR, "Contractor"),
    ]

    STATUS_ON_TRACK = "ON_TRACK"
    STATUS_MINOR_VARIANCE = "MINOR_VARIANCE"
    STATUS_MAJOR_VARIANCE = "MAJOR_VARIANCE"
    VARIANCE_STATUS_CHOICES = [
        (STATUS_ON_TRACK, "On Track"),
        (STATUS_MINOR_VARIANCE, "Minor Variance"),
        (STATUS_MAJOR_VARIANCE, "Major Variance"),
    ]

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="planned_vs_actual_records",
    )
    project_name = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Denormalized project name for lookups and RBAC filters",
    )
    planned_type = models.CharField(
        max_length=20,
        choices=PLANNED_TYPE_CHOICES,
        default=TYPE_SCL,
        db_index=True,
    )
    contractor = models.ForeignKey(
        "contractors.Contractor",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="planned_vs_actual_records",
    )
    contractor_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        db_index=True,
    )
    month = models.PositiveSmallIntegerField(db_index=True)
    year = models.PositiveSmallIntegerField(db_index=True)

    planned_value = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    actual_value = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    collection = models.DecimalField(max_digits=20, decimal_places=2, default=0)

    difference = models.DecimalField(
        max_digits=20, decimal_places=2, default=0, editable=False
    )
    achievement_percentage = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, editable=False
    )
    collection_percentage = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, editable=False
    )
    variance_percentage = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, editable=False
    )
    variance_status = models.CharField(
        max_length=20,
        choices=VARIANCE_STATUS_CHOICES,
        default=STATUS_ON_TRACK,
        editable=False,
        db_index=True,
    )

    reason_for_difference = models.TextField(blank=True, default="")
    remarks = models.TextField(blank=True, default="")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_planned_vs_actual",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_planned_vs_actual",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def projectName(self) -> str:
        return self.project_name

    @projectName.setter
    def projectName(self, value: str) -> None:
        self.project_name = value

    def clean(self):
        errors = {}
        if self.month is not None and not (1 <= self.month <= 12):
            errors["month"] = "month must be between 1 and 12."
        if self.year is not None and not (2000 <= self.year <= 2100):
            errors["year"] = "year must be between 2000 and 2100."
        if self.planned_type and self.planned_type not in {
            self.TYPE_SCL,
            self.TYPE_CONTRACTOR,
        }:
            errors["planned_type"] = "planned_type must be SCL or CONTRACTOR."
        if self.planned_value is not None and self.planned_value < 0:
            errors["planned_value"] = "planned_value must be >= 0."
        if self.actual_value is not None and self.actual_value < 0:
            errors["actual_value"] = "actual_value must be >= 0."
        if self.collection is not None and self.collection < 0:
            errors["collection"] = "collection must be >= 0."

        if self.planned_type == self.TYPE_SCL:
            if self.contractor_id or (self.contractor_name or "").strip():
                errors["contractor"] = "contractor must be empty for SCL records."
        elif self.planned_type == self.TYPE_CONTRACTOR:
            if not self.contractor_id and not (self.contractor_name or "").strip():
                errors["contractor_id"] = (
                    "contractor_id is required for CONTRACTOR records."
                )

        planned = _as_decimal(self.planned_value)
        actual = _as_decimal(self.actual_value)
        difference = planned - actual
        if difference > 0 and not (self.reason_for_difference or "").strip():
            errors["reason_for_difference"] = (
                "reason_for_difference is required when difference > 0."
            )

        if errors:
            raise ValidationError(errors)

    def recalculate(self) -> None:
        planned = _as_decimal(self.planned_value)
        actual = _as_decimal(self.actual_value)
        collection = _as_decimal(self.collection)
        self.difference = (planned - actual).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        self.achievement_percentage = _pct(actual, planned)
        self.collection_percentage = _pct(collection, actual)
        self.variance_percentage = _pct(self.difference, planned)
        self.variance_status = compute_variance_status(self.difference, planned)

    def save(self, *args, **kwargs):
        if self.project_id and not self.project_name:
            self.project_name = self.project.name
        if self.project_name:
            self.project_name = self.project_name.strip()
        if self.planned_type == self.TYPE_SCL:
            self.contractor = None
            self.contractor_name = None
        elif self.contractor_id:
            self.contractor_name = self.contractor.contractor_name
        elif self.contractor_name:
            self.contractor_name = str(self.contractor_name).strip()
        if self.reason_for_difference:
            self.reason_for_difference = self.reason_for_difference.strip()
        if self.remarks:
            self.remarks = self.remarks.strip()

        self.recalculate()
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        if self.planned_type == self.TYPE_CONTRACTOR and self.contractor_name:
            return (
                f"{self.project_name} — {self.contractor_name} "
                f"{self.month:02d}/{self.year} ({self.variance_status})"
            )
        return (
            f"{self.project_name} [SCL] {self.month:02d}/{self.year} "
            f"({self.variance_status})"
        )

    class Meta:
        ordering = ["project_name", "year", "month", "planned_type", "contractor_name"]
        verbose_name = "Planned vs Actual"
        verbose_name_plural = "Planned vs Actual Records"
        constraints = [
            models.UniqueConstraint(
                fields=["project_name", "planned_type", "month", "year"],
                condition=Q(planned_type="SCL"),
                name="pev_unique_scl_per_project_month",
            ),
            models.UniqueConstraint(
                fields=["project_name", "contractor", "month", "year"],
                condition=Q(planned_type="CONTRACTOR"),
                name="pev_unique_contractor_per_project_month",
            ),
        ]
        indexes = [
            models.Index(
                fields=["project_name", "year", "month"],
                name="pev_proj_year_month_idx",
            ),
            models.Index(
                fields=["project_name", "planned_type", "year", "month"],
                name="pev_proj_type_period_idx",
            ),
            models.Index(fields=["year", "month"], name="pev_year_month_idx"),
            models.Index(fields=["variance_status"], name="pev_variance_status_idx"),
        ]


PlannedVsActual = PlannedEarnedValue
