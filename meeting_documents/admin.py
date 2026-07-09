from django.contrib import admin

from .models import MeetingDocument


@admin.register(MeetingDocument)
class MeetingDocumentAdmin(admin.ModelAdmin):
    list_display = (
        "project",
        "meeting_type",
        "meeting_number",
        "title",
        "document_version",
        "uploaded_by",
        "uploaded_at",
        "is_active",
    )
    list_filter = ("meeting_type", "is_active", "meeting_date", "uploaded_at")
    search_fields = ("project__name", "title", "description", "meeting_number", "file_name")
    readonly_fields = (
        "original_file_size",
        "compressed_file_size",
        "compression_percentage",
        "content_type",
        "s3_key",
        "s3_url",
        "uploaded_at",
        "updated_at",
    )
