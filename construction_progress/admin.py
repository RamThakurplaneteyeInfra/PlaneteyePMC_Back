"""
Django admin registration for the Construction Progress app.
"""

from django.contrib import admin

from .models.construction_progress import ConstructionProgress


@admin.register(ConstructionProgress)
class ConstructionProgressAdmin(admin.ModelAdmin):
    """Admin view for Monthly Construction Progress records."""

    list_display = [
        "projectName",
        "progressMonth",
        "plannedProgress",
        "actualProgress",
        "variance",
        "performancePercentage",
        "created_at",
        "updated_at",
    ]
    list_filter = ["progressMonth", "created_at"]
    search_fields = ["projectName", "progressMonth"]
    readonly_fields = [
        "variance",
        "performancePercentage",
        "created_at",
        "updated_at",
    ]
    ordering = ["projectName", "progressMonth"]

    fieldsets = (
        (
            "Project & Month",
            {"fields": ("projectName", "progressMonth")},
        ),
        (
            "Progress Data",
            {
                "fields": ("plannedProgress", "actualProgress", "remarks"),
                "description": (
                    "Enter progress percentages (0–100). "
                    "Variance and performance are calculated automatically on save."
                ),
            },
        ),
        (
            "Auto-Calculated KPIs",
            {
                "fields": ("variance", "performancePercentage"),
                "description": "These fields are calculated automatically and cannot be edited directly.",
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
