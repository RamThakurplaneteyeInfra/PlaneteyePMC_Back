"""
Project Feedback Management — centralized repository of issues reported by
project teams. Standalone module; does not touch existing models/APIs.
"""

from django.conf import settings
from django.db import models

from projects.models import Project


class ProjectFeedback(models.Model):
    STATUS_OPEN = "Open"
    STATUS_IN_PROGRESS = "In Progress"
    STATUS_RESOLVED = "Resolved"
    STATUS_CLOSED = "Closed"
    STATUS_CHOICES = [
        (STATUS_OPEN, "Open"),
        (STATUS_IN_PROGRESS, "In Progress"),
        (STATUS_RESOLVED, "Resolved"),
        (STATUS_CLOSED, "Closed"),
    ]

    PRIORITY_LOW = "Low"
    PRIORITY_MEDIUM = "Medium"
    PRIORITY_HIGH = "High"
    PRIORITY_CRITICAL = "Critical"
    PRIORITY_CHOICES = [
        (PRIORITY_LOW, "Low"),
        (PRIORITY_MEDIUM, "Medium"),
        (PRIORITY_HIGH, "High"),
        (PRIORITY_CRITICAL, "Critical"),
    ]

    # Deterministic ordering weight for priority sorting.
    PRIORITY_RANK = {
        PRIORITY_LOW: 1,
        PRIORITY_MEDIUM: 2,
        PRIORITY_HIGH: 3,
        PRIORITY_CRITICAL: 4,
    }

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="feedback_items",
        db_index=True,
    )
    issue_title = models.CharField(max_length=255, db_index=True)
    issue_description = models.TextField()
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_OPEN,
        db_index=True,
    )
    priority = models.CharField(
        max_length=16,
        choices=PRIORITY_CHOICES,
        default=PRIORITY_MEDIUM,
        db_index=True,
    )

    # Optional S3 attachment (only metadata stored in DB).
    attachment_url = models.URLField(max_length=1000, blank=True, default="")
    attachment_name = models.CharField(max_length=255, blank=True, default="")
    attachment_size = models.PositiveBigIntegerField(default=0)
    attachment_type = models.CharField(max_length=120, blank=True, default="")
    # S3 object key kept internally for delete/presign; never required by API.
    attachment_key = models.CharField(max_length=700, blank=True, default="")

    remarks = models.TextField(blank=True, default="")

    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reported_feedback",
    )
    assigned_team_leader = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_feedback",
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Project Feedback"
        verbose_name_plural = "Project Feedback"
        indexes = [
            models.Index(fields=["project", "status"], name="feedback_proj_status_idx"),
            models.Index(fields=["project", "priority"], name="feedback_proj_priority_idx"),
            models.Index(fields=["reported_by", "created_at"], name="feedback_reporter_idx"),
            models.Index(fields=["is_active", "created_at"], name="feedback_active_created_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.issue_title} [{self.status}] (project={self.project_id})"

    @property
    def has_attachment(self) -> bool:
        return bool(self.attachment_url)


class FeedbackAuditLog(models.Model):
    ACTION_CREATED = "created"
    ACTION_UPDATED = "updated"
    ACTION_STATUS_CHANGED = "status_changed"
    ACTION_PRIORITY_CHANGED = "priority_changed"
    ACTION_ATTACHMENT_UPDATED = "attachment_updated"
    ACTION_DELETED = "deleted"
    ACTION_CHOICES = [
        (ACTION_CREATED, "Created"),
        (ACTION_UPDATED, "Updated"),
        (ACTION_STATUS_CHANGED, "Status Changed"),
        (ACTION_PRIORITY_CHANGED, "Priority Changed"),
        (ACTION_ATTACHMENT_UPDATED, "Attachment Updated"),
        (ACTION_DELETED, "Deleted"),
    ]

    feedback = models.ForeignKey(
        ProjectFeedback,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    feedback_id_snapshot = models.PositiveIntegerField(null=True, blank=True)
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="feedback_audit_logs",
    )
    action = models.CharField(max_length=32, choices=ACTION_CHOICES, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="feedback_audit_actions",
    )
    detail = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Feedback Audit Log"
        verbose_name_plural = "Feedback Audit Logs"

    def __str__(self) -> str:
        return f"{self.action} feedback={self.feedback_id_snapshot} @ {self.created_at}"
