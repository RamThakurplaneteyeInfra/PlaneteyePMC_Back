"""
Django admin registration for the Invoicing app.
"""

from django.contrib import admin

from .controllers.invoicing_metrics import metrics_from_record
from .models.invoicing_information import InvoicingInformation


@admin.register(InvoicingInformation)
class InvoicingInformationAdmin(admin.ModelAdmin):
    """Admin view for Invoicing Information records."""

    list_display = [
        "project_name",
        "invoice_type",
        "gross_billed",
        "gross_certified_billed",
        "display_difference",
        "display_certification_efficiency",
        "created_at",
        "updated_at",
    ]
    list_filter = ["invoice_type", "created_at"]
    search_fields = ["project_name"]
    readonly_fields = [
        "display_difference",
        "display_certification_efficiency",
        "created_at",
        "updated_at",
    ]
    ordering = ["project_name", "invoice_type"]

    fieldsets = (
        ("Project & Type", {"fields": ("project_name", "invoice_type")}),
        (
            "Billing Information",
            {
                "fields": (
                    "gross_billed",
                    "gross_certified_billed",
                ),
            },
        ),
        (
            "Computed (read-only)",
            {
                "fields": (
                    "display_difference",
                    "display_certification_efficiency",
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

    @admin.display(description="Difference")
    def display_difference(self, obj):
        return metrics_from_record(obj)["difference"]

    @admin.display(description="Certification efficiency (%)")
    def display_certification_efficiency(self, obj):
        return metrics_from_record(obj)["certification_efficiency"]
