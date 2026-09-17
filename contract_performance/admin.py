"""
Django admin registration for the Contract Performance app.
"""

from django.contrib import admin

from .models.contract_performance import ContractPerformance


@admin.register(ContractPerformance)
class ContractPerformanceAdmin(admin.ModelAdmin):
    """Admin view for Contract Performance records."""

    list_display = [
        "projectName",
        "billedValue",
        "actualReceiptValue",
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
                "fields": ("billedValue", "actualReceiptValue"),
                "description": (
                    "Enter Billed Value and Actual Receipt Value. "
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
