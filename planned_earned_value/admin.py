"""
Django admin registration for the Planned vs Earned Value app.
"""

from django.contrib import admin

from .models.planned_earned_value import PlannedEarnedValue


@admin.register(PlannedEarnedValue)
class PlannedEarnedValueAdmin(admin.ModelAdmin):
    """Admin view for Planned vs Earned Value records."""

    list_display = [
        "projectName",
        "plannedValue",
        "earnedValue",
        "variance",
        "variancePercentage",
        "performancePercentage",
        "created_at",
        "updated_at",
    ]
    list_filter = ["created_at"]
    search_fields = ["projectName"]
    readonly_fields = [
        "variance",
        "variancePercentage",
        "performancePercentage",
        "created_at",
        "updated_at",
    ]
    ordering = ["projectName"]

    fieldsets = (
        ("Project", {"fields": ("projectName",)}),
        (
            "Input Values",
            {
                "fields": ("plannedValue", "earnedValue"),
                "description": (
                    "Enter Planned Value (PV) and Earned Value (EV). "
                    "Calculated fields update automatically on save."
                ),
            },
        ),
        (
            "Auto-Calculated KPIs",
            {
                "fields": (
                    "variance",
                    "variancePercentage",
                    "performancePercentage",
                ),
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
