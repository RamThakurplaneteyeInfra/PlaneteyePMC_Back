"""
Shared business audit trail for production-critical mutations.

Domain-specific audits (UserManagementAuditLog, TestingDocumentAuditLog,
FeedbackAuditLog) remain; this table covers cross-cutting events that had
no dedicated trail (projects, DPR, EOT, contract values, site images, etc.).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class BusinessAuditLog(models.Model):
    ENTITY_PROJECT = "project"
    ENTITY_DPR = "dpr"
    ENTITY_EOT = "eot"
    ENTITY_CONTRACT_VALUE = "contract_value"
    ENTITY_SITE_IMAGE = "site_image"
    ENTITY_ASSIGNMENT = "assignment"
    ENTITY_TUTORIAL_VIDEO = "tutorial_video"
    ENTITY_MPR = "mpr"
    ENTITY_DRAWING = "drawing"

    ENTITY_CHOICES = [
        (ENTITY_PROJECT, "Project"),
        (ENTITY_DPR, "DPR"),
        (ENTITY_EOT, "EOT"),
        (ENTITY_CONTRACT_VALUE, "Contract Value"),
        (ENTITY_SITE_IMAGE, "Site Image"),
        (ENTITY_ASSIGNMENT, "Assignment"),
        (ENTITY_TUTORIAL_VIDEO, "Tutorial Video"),
        (ENTITY_MPR, "MPR"),
        (ENTITY_DRAWING, "Drawing"),
    ]

    ACTION_CREATED = "created"
    ACTION_UPDATED = "updated"
    ACTION_DELETED = "deleted"
    ACTION_SUBMITTED = "submitted"
    ACTION_APPROVED = "approved"
    ACTION_REJECTED = "rejected"
    ACTION_COMPLETED = "completed"
    ACTION_BILLING_COMPLETED = "billing_completed"
    ACTION_UPLOADED = "uploaded"
    ACTION_ASSIGNED = "assigned"
    ACTION_FAILED = "failed"

    ACTION_CHOICES = [
        (ACTION_CREATED, "Created"),
        (ACTION_UPDATED, "Updated"),
        (ACTION_DELETED, "Deleted"),
        (ACTION_SUBMITTED, "Submitted"),
        (ACTION_APPROVED, "Approved"),
        (ACTION_REJECTED, "Rejected"),
        (ACTION_COMPLETED, "Completed"),
        (ACTION_BILLING_COMPLETED, "Billing Completed"),
        (ACTION_UPLOADED, "Uploaded"),
        (ACTION_ASSIGNED, "Assigned"),
        (ACTION_FAILED, "Failed"),
    ]

    entity_type = models.CharField(max_length=40, choices=ENTITY_CHOICES, db_index=True)
    entity_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="business_audit_logs",
    )
    project_name = models.CharField(max_length=255, blank=True, default="", db_index=True)
    action = models.CharField(max_length=40, choices=ACTION_CHOICES, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="business_audit_actions",
    )
    detail = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["entity_type", "entity_id", "-created_at"],
                name="biz_audit_entity_created_idx",
            ),
            models.Index(
                fields=["project", "-created_at"],
                name="biz_audit_project_created_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.entity_type}:{self.entity_id} {self.action}"
