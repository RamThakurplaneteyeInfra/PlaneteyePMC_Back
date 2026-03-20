from django.contrib import admin
from .models import InvoicingInformation


@admin.register(InvoicingInformation)
class InvoicingInformationAdmin(admin.ModelAdmin):
    list_display = (
        "project_name",
        "gross_billed",
        "net_billed_without_vat",
        "net_collected",
        "net_due",
        "created_by",
        "updated_by",
        "created_at",
        "updated_at",
    )
    list_filter = ("created_by", "updated_by", "created_at")
    search_fields = ("project_name", "created_by", "updated_by")
    readonly_fields = (
        "net_due",  # Auto-calculated
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (None, {
            "fields": ("project_name",)
        }),
        ("Billing Information", {
            "fields": ("gross_billed", "net_billed_without_vat", "net_collected", "net_due")
        }),
        ("Tracking", {
            "fields": ("created_by", "updated_by")
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at")
        }),
    )
