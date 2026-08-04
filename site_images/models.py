"""
Site progress photos stored in Cloudinary (metadata in DB).
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class SiteProgressImage(models.Model):
    """One uploaded site photo for a project month."""

    STORAGE_S3 = "s3"
    STORAGE_CLOUDINARY = "cloudinary"
    STORAGE_CHOICES = [
        (STORAGE_S3, "AWS S3"),
        (STORAGE_CLOUDINARY, "Cloudinary"),
    ]

    project_name = models.CharField(max_length=255, db_index=True)
    month = models.PositiveSmallIntegerField(db_index=True)
    year = models.PositiveSmallIntegerField(db_index=True)
    title = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        default="",
        help_text="Optional display title for the site image",
    )
    image_url = models.URLField(max_length=500)
    cloudinary_public_id = models.CharField(
        max_length=500,
        unique=True,
        help_text="Storage key (S3 object key or Cloudinary public_id)",
    )
    storage_backend = models.CharField(
        max_length=20,
        choices=STORAGE_CHOICES,
        default=STORAGE_CLOUDINARY,
        db_index=True,
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_site_images",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        errors = {}
        if self.month is not None and not (1 <= self.month <= 12):
            errors["month"] = "month must be between 1 and 12."
        if self.year is not None and not (2000 <= self.year <= 2100):
            errors["year"] = "year must be between 2000 and 2100."
        if not (self.project_name or "").strip():
            errors["project_name"] = "project_name is required."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.project_name:
            self.project_name = self.project_name.strip()
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.project_name} ({self.month:02d}/{self.year}) — {self.cloudinary_public_id}"

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Site Progress Image"
        verbose_name_plural = "Site Progress Images"
        indexes = [
            models.Index(
                fields=["project_name", "year", "month"],
                name="site_img_proj_period_idx",
            ),
        ]
