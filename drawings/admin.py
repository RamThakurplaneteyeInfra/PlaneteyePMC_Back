"""
Django admin registration for the Drawings app.

DrawingSummary is kept as a read-only legacy view.
DrawingRegisterItem is the primary data source.
"""

from django.contrib import admin

from .models.drawing import DrawingSummary
from .models.drawing_file import DrawingFile
from .models.drawing_register import DrawingRegisterItem, DrawingWorkflowEvent


class DrawingWorkflowEventInline(admin.TabularInline):
    model = DrawingWorkflowEvent
    extra = 0
    fields = ["action", "event_date", "notes"]


class DrawingFileInline(admin.TabularInline):
    model = DrawingFile
    extra = 0
    fields = [
        "revision",
        "original_filename",
        "file_size",
        "content_type",
        "is_active",
        "created_at",
    ]
    readonly_fields = ["created_at"]
    show_change_link = True


@admin.register(DrawingRegisterItem)
class DrawingRegisterItemAdmin(admin.ModelAdmin):
    list_display = [
        "project",
        "sr_no",
        "revision",
        "drawing_name",
        "contractor_name",
        "remarks",
        "submitted_date",
        "approved_date",
    ]
    list_filter = ["project", "contractor_name", "remarks"]
    search_fields = ["drawing_name", "contractor_name", "remarks", "project__name"]
    inlines = [DrawingWorkflowEventInline, DrawingFileInline]
    autocomplete_fields = ["project"]
    ordering = ["project__name", "sr_no", "revision"]


@admin.register(DrawingFile)
class DrawingFileAdmin(admin.ModelAdmin):
    list_display = [
        "original_filename",
        "drawing_register",
        "revision",
        "file_size",
        "is_active",
        "created_at",
    ]
    list_filter = ["is_active", "revision"]
    search_fields = ["original_filename", "drawing_register__drawing_name"]
    readonly_fields = ["s3_key", "file_url", "created_at", "updated_at"]
    autocomplete_fields = ["drawing_register", "uploaded_by"]


@admin.register(DrawingSummary)
class DrawingSummaryAdmin(admin.ModelAdmin):
    """
    Legacy read-only admin view for DrawingSummary records.

    These records are no longer updated by the application — KPI data
    is computed directly from DrawingRegisterItem. This admin is retained
    for reference only.
    """

    list_display = [
        "project",
        "month",
        "year",
        "submitted_drawings",
        "approved_drawings",
        "created_at",
        "updated_at",
    ]
    list_filter = ["year", "month"]
    search_fields = ["project__name"]
    readonly_fields = [
        "project",
        "month",
        "year",
        "submitted_drawings",
        "approved_drawings",
        "created_at",
        "updated_at",
    ]
    ordering = ["project__name", "year", "month"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
