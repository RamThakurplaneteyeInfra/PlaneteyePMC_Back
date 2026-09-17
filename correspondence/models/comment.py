from django.conf import settings
from django.db import models
from django.utils import timezone

from .correspondence import CorrespondenceDocument


class CorrespondenceComment(models.Model):
    """An optional historical comment on an inbound correspondence document."""

    correspondence = models.ForeignKey(
        CorrespondenceDocument,
        on_delete=models.CASCADE,
        related_name="comments",
    )
    comment = models.TextField()
    commented_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="correspondence_comments",
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(
                fields=["correspondence", "is_active", "created_at"],
                name="corr_comment_active_time_idx",
            ),
        ]
        verbose_name = "Correspondence Comment"
        verbose_name_plural = "Correspondence Comments"

    def __str__(self) -> str:
        return f"Comment #{self.pk} on correspondence #{self.correspondence_id}"
