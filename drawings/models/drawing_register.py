"""
Per-drawing register and workflow history.

DrawingRegisterItem is the single source of truth for all drawing KPI metrics.
DrawingSummary is a legacy model kept for DB compatibility only.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Max
from django.utils import timezone

from projects.models import Project


class DrawingRegisterItem(models.Model):
    """One design/drawing row in the project register (supports revisions)."""

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="drawing_register_items",
        db_index=True,
    )
    sr_no = models.PositiveIntegerField(
        help_text="Serial number within the project register",
    )
    drawing_name = models.CharField(
        max_length=500,
        help_text="Design and drawing title",
    )
    contractor_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_index=True,
        help_text="Contractor associated with this drawing",
    )
    revision = models.PositiveSmallIntegerField(
        default=1,
        help_text="Drawing revision number",
    )
    remarks = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Current status / remarks (e.g. Approved, Pending)",
    )

    # Optional direct dates (fallback when workflow events are absent)
    submitted_date = models.DateField(null=True, blank=True)
    consultant_comments_date = models.DateField(null=True, blank=True)
    resubmitted_date = models.DateField(null=True, blank=True)
    approved_date = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["project__name", "sr_no", "revision"]
        verbose_name = "Drawing Register Item"
        verbose_name_plural = "Drawing Register Items"
        constraints = [
            models.UniqueConstraint(
                fields=["project", "sr_no", "revision"],
                name="drawing_register_unique_sr_revision",
            ),
        ]
        indexes = [
            models.Index(
                fields=["project", "sr_no"],
                name="draw_reg_proj_sr_idx",
            ),
            models.Index(
                fields=["project", "contractor_name"],
                name="draw_reg_proj_contr_idx",
            ),
        ]

    @property
    def project_name(self) -> str:
        return self.project.name if self.project_id else ""

    @classmethod
    def next_sr_no(cls, project_id: int) -> int:
        current = cls.objects.filter(project_id=project_id).aggregate(
            max_sr=Max("sr_no")
        )["max_sr"]
        return (current or 0) + 1

    def clean(self):
        if self.revision < 1:
            raise ValidationError({"revision": "revision must be >= 1."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.project_name} #{self.sr_no} — {self.drawing_name} (Rev {self.revision})"


class DrawingWorkflowEvent(models.Model):
    """Workflow stage transition for a drawing register item."""

    ACTION_SUBMITTED = "SUBMITTED"
    ACTION_CONSULTANT_COMMENTED = "CONSULTANT_COMMENTED"
    ACTION_RESUBMITTED = "RESUBMITTED"
    ACTION_APPROVED = "APPROVED"

    ACTION_CHOICES = [
        (ACTION_SUBMITTED, "Submission by Contractor"),
        (ACTION_CONSULTANT_COMMENTED, "Comments/Approval by Consultant"),
        (ACTION_RESUBMITTED, "Re-submission by Contractor"),
        (ACTION_APPROVED, "Approved by Consultant"),
    ]

    drawing = models.ForeignKey(
        DrawingRegisterItem,
        on_delete=models.CASCADE,
        related_name="workflow_events",
        db_index=True,
    )
    action = models.CharField(max_length=32, choices=ACTION_CHOICES, db_index=True)
    event_date = models.DateField(db_index=True)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["event_date", "created_at", "id"]
        verbose_name = "Drawing Workflow Event"
        verbose_name_plural = "Drawing Workflow Events"
        indexes = [
            models.Index(
                fields=["drawing", "action", "event_date"],
                name="draw_wf_action_dt_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.drawing_id} — {self.action} @ {self.event_date}"
