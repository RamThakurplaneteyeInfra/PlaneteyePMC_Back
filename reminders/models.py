"""
PO-31 Reminders — user-scheduled project reminders (not Alerts / Tasks).
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Reminder(models.Model):
    STATUS_PENDING = "pending"
    STATUS_COMPLETED = "completed"
    STATUS_DISMISSED = "dismissed"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_DISMISSED, "Dismissed"),
    ]

    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        related_name="reminders",
        db_index=True,
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    due_at = models.DateTimeField(
        db_index=True,
        help_text="When the reminder is due (assignee is notified at/after this time)",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="assigned_reminders",
        db_index=True,
        help_text="User who should receive the reminder notification",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_reminders",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )
    snoozed_until = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="If set, effective due time for notifications/lists",
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    dismissed_at = models.DateTimeField(null=True, blank=True)
    notified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the due notification was last sent",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["due_at", "id"]
        verbose_name = "Reminder"
        verbose_name_plural = "Reminders"
        indexes = [
            models.Index(
                fields=["status", "due_at"],
                name="rem_status_due_idx",
            ),
            models.Index(
                fields=["project", "status", "due_at"],
                name="rem_proj_status_due_idx",
            ),
            models.Index(
                fields=["assigned_to", "status", "due_at"],
                name="rem_assignee_due_idx",
            ),
            models.Index(
                fields=["status", "notified_at", "due_at"],
                name="rem_notify_scan_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.status}) @ {self.due_at}"

    @property
    def effective_due_at(self):
        """Snooze overrides due_at while snoozed_until is in the future / set."""
        if self.snoozed_until is not None:
            return self.snoozed_until
        return self.due_at

    def clean(self):
        errors = {}
        if self.due_at is None:
            errors["due_at"] = "due_at is required."
        if self.assigned_to_id and self.project_id:
            # Soft check only — hard RBAC is in the serializer/view.
            pass
        if errors:
            raise ValidationError(errors)

    def mark_completed(self, *, actor=None) -> None:
        self.status = self.STATUS_COMPLETED
        self.completed_at = timezone.now()
        self.dismissed_at = None
        self.save(
            update_fields=["status", "completed_at", "dismissed_at", "updated_at"]
        )

    def mark_dismissed(self, *, actor=None) -> None:
        self.status = self.STATUS_DISMISSED
        self.dismissed_at = timezone.now()
        self.completed_at = None
        self.save(
            update_fields=["status", "dismissed_at", "completed_at", "updated_at"]
        )

    def snooze(self, *, until) -> None:
        if until is None:
            raise ValidationError({"snoozed_until": "Snooze target datetime is required."})
        if until <= timezone.now():
            raise ValidationError(
                {"snoozed_until": "Snooze target must be in the future."}
            )
        self.status = self.STATUS_PENDING
        self.snoozed_until = until
        self.notified_at = None  # allow re-notify after new due
        self.completed_at = None
        self.dismissed_at = None
        self.save(
            update_fields=[
                "status",
                "snoozed_until",
                "notified_at",
                "completed_at",
                "dismissed_at",
                "updated_at",
            ]
        )
