"""
Django admin registration for the Contract Values app.
"""

from django.contrib import admin

from .models.contract_value import ContractValue


@admin.register(ContractValue)
class ContractValueAdmin(admin.ModelAdmin):
    """Admin view for Contract Value records."""

    list_display = [
        "projectName",
        "contractType",
        "originalContractValue",
        "approvedVO",
        "approvedVOPercentage",
        "revisedContractValue",
        "potentialPendingVO",
        "created_at",
        "updated_at",
    ]
    list_filter = ["contractType", "created_at"]
    search_fields = ["projectName"]
    readonly_fields = [
        "approvedVOPercentage",
        "revisedContractValue",
        "created_at",
        "updated_at",
    ]
    ordering = ["projectName", "contractType"]

    fieldsets = (
        ("Project & Type", {"fields": ("projectName", "contractType")}),
        (
            "Contract Financials",
            {
                "fields": (
                    "originalContractValue",
                    "approvedVO",
                    "potentialPendingVO",
                ),
            },
        ),
        (
            "Auto-Calculated KPIs",
            {
                "fields": ("approvedVOPercentage", "revisedContractValue"),
                "description": "Calculated automatically on save. Cannot be edited directly.",
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
