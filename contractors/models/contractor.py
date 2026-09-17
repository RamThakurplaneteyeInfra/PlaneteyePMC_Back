"""Contractor Master — single source of truth for project contractors."""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from projects.models import Project


class Contractor(models.Model):
    """A contractor assigned to a project."""

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        INACTIVE = "INACTIVE", "Inactive"

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="contractors",
        db_index=True,
    )
    contractor_name = models.CharField(max_length=255, db_index=True)
    contractor_code = models.CharField(max_length=50, blank=True, default="")
    contact_person = models.CharField(max_length=255, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    phone = models.CharField(max_length=30, blank=True, default="")
    address = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True,
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["project__name", "contractor_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["project", "contractor_name"],
                name="contractor_unique_name_per_project",
            )
        ]
        indexes = [
            models.Index(fields=["project", "status"], name="contractor_project_status_idx"),
        ]
        verbose_name = "Contractor"
        verbose_name_plural = "Contractors"

    def clean(self):
        errors = {}
        name = (self.contractor_name or "").strip()
        if not name:
            errors["contractor_name"] = "contractor_name is required."
        else:
            self.contractor_name = name

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.project.name} — {self.contractor_name} [{self.status}]"

    def to_api_dict(self, *, full: bool = False) -> dict:
        payload = {
            "id": self.id,
            "contractor_name": self.contractor_name,
            "status": self.status,
        }
        if full:
            payload.update(
                {
                    "contractor_code": self.contractor_code,
                    "contact_person": self.contact_person,
                    "email": self.email,
                    "phone": self.phone,
                    "address": self.address,
                    "created_at": self.created_at,
                    "updated_at": self.updated_at,
                }
            )
        return payload
