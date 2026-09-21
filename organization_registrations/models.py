"""
Public organization onboarding requests.

These rows are requests only — they must never create Django users, JWTs,
or tenant/workspace records.
"""

import uuid
from pathlib import Path

from django.db import models
from django.utils import timezone


def organization_logo_upload_to(instance, filename):
    ext = Path(filename or "").suffix.lower() or ".bin"
    now = timezone.now()
    return f"organization_registrations/logos/{now:%Y/%m}/{uuid.uuid4().hex}{ext}"


class OrganizationRegistration(models.Model):
    STATUS_PENDING = "pending"
    STATUS_CONTACTED = "contacted"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_CONTACTED, "Contacted"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
    ]

    legal_name = models.CharField(max_length=255)
    display_name = models.CharField(max_length=255)
    office_address = models.TextField()
    city = models.CharField(max_length=120)
    pin = models.CharField(max_length=20)
    phone = models.CharField(max_length=30)
    official_email = models.EmailField()
    admin_name = models.CharField(max_length=255)
    admin_email = models.EmailField()

    # Optional on disk: production (Vercel) stores logos in S3 only.
    logo = models.FileField(
        upload_to=organization_logo_upload_to,
        blank=True,
        null=True,
    )
    logo_original_name = models.CharField(max_length=255, blank=True, default="")
    logo_s3_key = models.CharField(max_length=700, blank=True, default="")
    logo_s3_url = models.URLField(max_length=1000, blank=True, default="")

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )
    submitted_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-submitted_at"]
        verbose_name = "Organization Registration"
        verbose_name_plural = "Organization Registrations"

    def __str__(self) -> str:
        return f"{self.display_name} [{self.status}]"

    def logo_public_url(self, request=None) -> str:
        if self.logo_s3_url:
            return self.logo_s3_url
        if not self.logo:
            return ""
        url = self.logo.url
        if request is not None:
            return request.build_absolute_uri(url)
        return url
