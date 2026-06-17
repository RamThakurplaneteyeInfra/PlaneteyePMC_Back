"""
Django admin registration for the Drawings app.

DrawingSummary is kept as a read-only legacy view.
DrawingRegisterItem is the primary data source.
"""

from django.contrib import admin

from .models.drawing import DrawingSummary
from .models.drawing_register import DrawingRegisterItem, DrawingWorkflowEvent


class DrawingWorkflowEventInline(admin.TabularInline):
    model = DrawingWorkflowEvent
    extra = 0
    fields = ["action", "event_date", "notes"]


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
    inlines = [DrawingWorkflowEventInline]
    autocomplete_fields = ["project"]
    ordering = ["project__name", "sr_no", "revision"]


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
