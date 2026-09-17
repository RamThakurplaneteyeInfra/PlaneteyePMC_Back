from django.contrib import admin

from tutorial_videos.models import TutorialVideo


@admin.register(TutorialVideo)
class TutorialVideoAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "title",
        "section",
        "status",
        "is_active",
        "file_size",
        "duration_seconds",
        "created_by",
        "created_at",
    ]
    list_filter = ["section", "status", "is_active", "created_at"]
    search_fields = [
        "title",
        "description",
        "section",
        "optimized_s3_key",
        "original_filename",
    ]
    readonly_fields = [
        "status",
        "processing_error",
        "temp_s3_key",
        "optimized_s3_key",
        "video_url",
        "original_filename",
        "original_file_size",
        "original_content_type",
        "file_size",
        "duration_seconds",
        "width",
        "height",
        "compression_ratio",
        "processing_ms",
        "created_by",
        "created_at",
        "updated_at",
    ]
    ordering = ["-created_at"]
