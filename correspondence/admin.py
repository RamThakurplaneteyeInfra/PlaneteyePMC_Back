"""
Django admin registration for the Correspondence app.
"""

from django.contrib import admin

from .models.correspondence import CorrespondenceStatus


@admin.register(CorrespondenceStatus)
class CorrespondenceStatusAdmin(admin.ModelAdmin):
    """Admin view for monthly CorrespondenceStatus records."""

    list_display = [
        "project",
        "month",
        "year",
        "correspondence_type",
        "correspondence_received",
        "correspondence_delivered",
        "created_at",
        "updated_at",
    ]
    list_filter = ["year", "month", "correspondence_type", "created_at"]
    search_fields = ["project__name"]
    readonly_fields = ["created_at", "updated_at"]
    ordering = ["project__name", "year", "month", "correspondence_type"]

    fieldsets = (
        (
            "Project & Period",
            {"fields": ("project", "month", "year", "correspondence_type")},
        ),
        (
            "Correspondence Counts",
            {"fields": ("correspondence_received", "correspondence_delivered")},
        ),
        (
            "Timestamps",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )
