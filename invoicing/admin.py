"""
Django admin registration for the Invoicing app.
"""

from django.contrib import admin

from .models.invoicing_information import InvoicingInformation


@admin.register(InvoicingInformation)
class InvoicingInformationAdmin(admin.ModelAdmin):
    """Admin view for Invoicing Information records."""

    list_display = [
        "projectName",
        "invoiceType",
        "grossBilled",
        "netBilledWithoutVAT",
        "netCollected",
        "netDue",
        "created_at",
        "updated_at",
    ]
    list_filter = ["invoiceType", "created_at"]
    search_fields = ["projectName"]
    readonly_fields = ["netDue", "created_at", "updated_at"]
    ordering = ["projectName", "invoiceType"]

    fieldsets = (
        ("Project & Type", {"fields": ("projectName", "invoiceType")}),
        (
            "Billing Information",
            {
                "fields": (
                    "grossBilled",
                    "netBilledWithoutVAT",
                    "netCollected",
                ),
            },
        ),
        (
            "Auto-Calculated",
            {
                "fields": ("netDue",),
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
