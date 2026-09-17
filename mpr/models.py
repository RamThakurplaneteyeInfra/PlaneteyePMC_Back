"""
MPRReport — persisted immutable snapshot + generated PDF/Excel artifacts.
"""

from django.conf import settings
from django.db import models


class MPRReport(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_GENERATING = "generating"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_ARCHIVED = "archived"
    # Legacy alias kept for code that may still reference Phase-1 name
    STATUS_GENERATED = STATUS_COMPLETED

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_GENERATING, "Generating"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
        (STATUS_ARCHIVED, "Archived"),
    ]

    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        related_name="mpr_reports",
        db_index=True,
    )
    report_month = models.PositiveSmallIntegerField(
        help_text="Month number 1–12",
    )
    report_year = models.PositiveSmallIntegerField(
        help_text="Four-digit year",
    )
    version = models.PositiveIntegerField(
        default=1,
        help_text="Monotonic version per project+month (regenerate creates a new version)",
    )
    is_latest = models.BooleanField(
        default=True,
        db_index=True,
        help_text="True for the newest version of this project+month",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
        db_index=True,
    )
    snapshot_json = models.JSONField(
        null=True,
        blank=True,
        help_text="Immutable MPR payload used for PDF/Excel generation",
    )
    pdf_key = models.CharField(max_length=700, blank=True, default="")
    pdf_url = models.URLField(max_length=1000, blank=True, default="")
    excel_key = models.CharField(max_length=700, blank=True, default="")
    excel_url = models.URLField(max_length=1000, blank=True, default="")
    error_message = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="Safe client-facing failure summary (no stack traces)",
    )
    generation_started_at = models.DateTimeField(null=True, blank=True)
    generated_at = models.DateTimeField(null=True, blank=True)
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generated_mpr_reports",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-report_year", "-report_month", "-version", "-id"]
        verbose_name = "MPR Report"
        verbose_name_plural = "MPR Reports"
        constraints = [
            models.UniqueConstraint(
                fields=["project", "report_year", "report_month", "version"],
                name="mpr_unique_project_year_month_version",
            ),
        ]
        indexes = [
            models.Index(
                fields=["project", "report_year", "report_month"],
                name="mpr_proj_period_idx",
            ),
            models.Index(
                fields=["project", "is_latest", "-report_year", "-report_month"],
                name="mpr_proj_latest_idx",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"MPR {self.project_id} "
            f"{self.report_year}-{self.report_month:02d} v{self.version}"
        )

    @property
    def report_month_key(self) -> str:
        return f"{self.report_year:04d}-{self.report_month:02d}"

    @property
    def pdf_available(self) -> bool:
        return bool(self.pdf_key or self.pdf_url) and self.status == self.STATUS_COMPLETED

    @property
    def excel_available(self) -> bool:
        return bool(self.excel_key or self.excel_url) and self.status == self.STATUS_COMPLETED
