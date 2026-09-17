"""
Item-based Issue / Concern / Risk / Action register per project.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Bottleneck(models.Model):
    TYPE_ISSUE = "ISSUE"
    TYPE_CONCERN = "CONCERN"
    TYPE_RISK = "RISK"
    TYPE_ACTION = "ACTION"

    TYPE_CHOICES = [
        (TYPE_ISSUE, "Issue"),
        (TYPE_CONCERN, "Concern"),
        (TYPE_RISK, "Risk"),
        (TYPE_ACTION, "Action"),
    ]

    PRIORITY_LOW = "LOW"
    PRIORITY_MEDIUM = "MEDIUM"
    PRIORITY_HIGH = "HIGH"
    PRIORITY_CRITICAL = "CRITICAL"

    PRIORITY_CHOICES = [
        (PRIORITY_LOW, "Low"),
        (PRIORITY_MEDIUM, "Medium"),
        (PRIORITY_HIGH, "High"),
        (PRIORITY_CRITICAL, "Critical"),
    ]

    STATUS_OPEN = "OPEN"
    STATUS_IN_PROGRESS = "IN_PROGRESS"
    STATUS_CLOSED = "CLOSED"

    STATUS_CHOICES = [
        (STATUS_OPEN, "Open"),
        (STATUS_IN_PROGRESS, "In Progress"),
        (STATUS_CLOSED, "Closed"),
    ]

    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        related_name="bottlenecks",
        db_index=True,
    )
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, db_index=True)
    description = models.TextField()
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, db_index=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_OPEN,
        db_index=True,
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_bottlenecks",
    )
    target_date = models.DateField(null=True, blank=True, db_index=True)
    remarks = models.TextField(blank=True, default="")
    client_id = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        db_index=True,
        help_text="Frontend UUID for dashboard sync via project-logs",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_bottlenecks",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_bottlenecks",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["project", "type"]),
            models.Index(fields=["project", "status"]),
            models.Index(fields=["project", "priority"]),
            models.Index(fields=["project", "target_date"]),
            # Default list: filter(project_id=…).order_by("-created_at")
            models.Index(fields=["project", "-created_at"], name="bn_proj_created_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["project", "client_id"],
                condition=models.Q(client_id__isnull=False),
                name="unique_bottleneck_client_id_per_project",
            ),
        ]
        verbose_name = "Bottleneck Item"
        verbose_name_plural = "Bottleneck Items"

    def __str__(self):
        return f"{self.type} #{self.pk} — {self.project.name}"

    def clean(self):
        super().clean()
        if self.target_date is not None:
            reference_date = (
                self.created_at.date()
                if self.pk and self.created_at
                else timezone.localdate()
            )
            if self.target_date < reference_date:
                raise ValidationError(
                    {"target_date": "Target date cannot be earlier than the created date."}
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def is_overdue(self) -> bool:
        if not self.target_date or self.status == self.STATUS_CLOSED:
            return False
        return self.target_date < timezone.localdate()
