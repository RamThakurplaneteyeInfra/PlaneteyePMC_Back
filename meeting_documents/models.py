from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from projects.models import Project


class MeetingDocument(models.Model):
    MEETING_TYPE_MOM = "MOM"
    MEETING_TYPE_EDL = "EDL"
    MEETING_TYPE_CHOICES = [
        (MEETING_TYPE_MOM, "Minutes of Meeting"),
        (MEETING_TYPE_EDL, "Engineering Decision Log"),
    ]

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="meeting_documents",
        db_index=True,
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_meeting_documents",
    )
    meeting_type = models.CharField(
        max_length=10,
        choices=MEETING_TYPE_CHOICES,
        db_index=True,
    )
    title = models.CharField(max_length=255, db_index=True)
    description = models.TextField(blank=True)
    meeting_date = models.DateField(db_index=True)
    meeting_number = models.CharField(max_length=80, blank=True, db_index=True)
    document_version = models.PositiveIntegerField(default=1, db_index=True)
    file_name = models.CharField(max_length=255)
    original_file_size = models.PositiveBigIntegerField(default=0)
    compressed_file_size = models.PositiveBigIntegerField(default=0)
    compression_percentage = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=0,
    )
    content_type = models.CharField(max_length=120)
    s3_key = models.CharField(max_length=700, unique=True)
    s3_url = models.URLField(max_length=1000)
    uploaded_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_meeting_documents",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_meeting_documents",
    )

    class Meta:
        ordering = ["-meeting_date", "-document_version", "-uploaded_at"]
        indexes = [
            models.Index(
                fields=["project", "meeting_type", "meeting_date"],
                name="meet_doc_proj_type_date_idx",
            ),
            models.Index(
                fields=["project", "meeting_type", "meeting_number"],
                name="meet_doc_proj_type_no_idx",
            ),
            models.Index(
                fields=["project", "is_active", "uploaded_at"],
                name="meet_doc_active_upload_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "project",
                    "meeting_type",
                    "meeting_number",
                    "title",
                    "document_version",
                ],
                name="meet_doc_unique_number_version",
            ),
        ]
        verbose_name = "Meeting Document"
        verbose_name_plural = "Meeting Documents"

    @property
    def project_name(self) -> str:
        return self.project.name if self.project_id else ""

    def clean(self):
        errors = {}
        if self.meeting_type not in {self.MEETING_TYPE_MOM, self.MEETING_TYPE_EDL}:
            errors["meeting_type"] = "meeting_type must be MOM or EDL."
        if not (self.title or "").strip():
            errors["title"] = "title is required."
        if self.document_version < 1:
            errors["document_version"] = "document_version must be >= 1."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.title:
            self.title = self.title.strip()
        if self.meeting_number:
            self.meeting_number = self.meeting_number.strip()
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        number = self.meeting_number or self.title
        return f"{self.project_name} {self.meeting_type}-{number} v{self.document_version}"
