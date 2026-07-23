"""
Django admin registration for the Contract Values app.
"""

from django.contrib import admin

from .models.contract_value import ContractValue


@admin.register(ContractValue)
class ContractValueAdmin(admin.ModelAdmin):
    list_display = [
        "project_name",
        "contract_type",
        "original_contract_value",
        "excess_value",
        "saving",
        "cos",
        "created_at",
        "updated_at",
    ]
    list_filter = ["contract_type", "created_at"]
    search_fields = ["project_name"]
    readonly_fields = ["created_at", "updated_at"]
    ordering = ["project_name", "contract_type"]

    fieldsets = (
        ("Project & Type", {"fields": ("project_name", "contract_type")}),
        (
            "Contract Financials",
            {
                "fields": (
                    "original_contract_value",
                    "excess_value",
                    "saving",
                    "cos",
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
