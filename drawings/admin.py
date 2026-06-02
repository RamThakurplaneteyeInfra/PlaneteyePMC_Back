"""
Django admin registration for the Drawings app.
"""

from django.contrib import admin

from .models.drawing import DrawingSummary


@admin.register(DrawingSummary)
class DrawingSummaryAdmin(admin.ModelAdmin):
    """Admin view for monthly Drawing Summary records."""

    list_display = [
        "project",
        "month",
        "year",
        "submitted_drawings",
        "approved_drawings",
        "created_at",
        "updated_at",
    ]
    list_filter = ["year", "month", "created_at"]
    search_fields = ["project__name"]
    readonly_fields = ["created_at", "updated_at"]
    ordering = ["project__name", "year", "month"]
    autocomplete_fields = ["project"]

    fieldsets = (
        ("Project & Period", {"fields": ("project", "month", "year")}),
        ("Counts", {"fields": ("submitted_drawings", "approved_drawings")}),
        (
            "Timestamps",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )
