"""
Django admin registration for the Project Quality Status app.
"""

from django.contrib import admin

from .models.project_quality_status import ProjectQualityStatus


@admin.register(ProjectQualityStatus)
class ProjectQualityStatusAdmin(admin.ModelAdmin):
    """Admin view for Project Quality Status records."""

    list_display = [
        "projectName",
        "totalTestsConducted",
        "totalTestsPassed",
        "variance",
        "performancePercentage",
        "created_at",
        "updated_at",
    ]
    list_filter = ["created_at"]
    search_fields = ["projectName"]
    readonly_fields = [
        "variance",
        "performancePercentage",
        "created_at",
        "updated_at",
    ]
    ordering = ["projectName"]

    fieldsets = (
        ("Project", {"fields": ("projectName",)}),
        (
            "Test Counts",
            {
                "fields": ("totalTestsConducted", "totalTestsPassed"),
                "description": (
                    "Enter test counts. "
                    "Calculated fields update automatically on save."
                ),
            },
        ),
        (
            "Auto-Calculated KPIs",
            {
                "fields": ("variance", "performancePercentage"),
                "description": (
                    "These fields are calculated automatically and cannot be edited directly."
                ),
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )
