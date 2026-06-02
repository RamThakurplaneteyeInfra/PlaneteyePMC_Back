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
        "value_type",
        "month",
        "year",
        "plannedValue",
        "earnedValue",
        "variance",
        "variancePercentage",
        "performancePercentage",
        "created_at",
        "updated_at",
    ]
    list_filter = ["value_type", "year", "month", "created_at"]
    search_fields = ["projectName"]
    readonly_fields = [
        "variance",
        "variancePercentage",
        "performancePercentage",
        "created_at",
        "updated_at",
    ]
    ordering = ["projectName", "year", "month", "value_type"]

    fieldsets = (
        ("Project & Period", {"fields": ("projectName", "value_type", "month", "year")}),
        ("Input Values", {"fields": ("plannedValue", "earnedValue")}),
        (
            "Auto-Calculated KPIs",
            {"fields": ("variance", "variancePercentage", "performancePercentage")},
        ),
        (
            "Timestamps",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )
