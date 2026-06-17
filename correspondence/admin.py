"""
Django admin registration for the Correspondence app.
"""

from django.contrib import admin

from .models.correspondence import CorrespondenceDocument
from .models.scl_delivered_summary import SCLDeliveredCorrespondenceSummary


@admin.register(SCLDeliveredCorrespondenceSummary)
class SCLDeliveredCorrespondenceSummaryAdmin(admin.ModelAdmin):
    list_display = [
        "project_name",
        "month",
        "year",
        "view",
        "client_received",
        "client_delivered",
        "client_pending",
        "contractor_received",
        "contractor_delivered",
        "contractor_pending",
        "other_agency_received",
        "other_agency_delivered",
        "other_agency_pending",
        "total_received",
        "total_delivered",
        "total_pending",
        "updated_at",
    ]
    list_filter = ["view", "year", "month"]
    search_fields = ["project_name"]


@admin.register(CorrespondenceDocument)
class CorrespondenceDocumentAdmin(admin.ModelAdmin):
    list_display = [
        "project_name",
        "month",
        "year",
        "correspondence_type",
        "sr_no",
        "received_date",
        "deadline_date",
        "delivered_date",
        "delivered_status",
        "created_at",
    ]
    list_filter = [
        "correspondence_type",
        "delivered_status",
        "received_date",
        "created_at",
    ]
    search_fields = ["project_name", "description"]
    readonly_fields = [
        "sr_no",
        "deadline_date",
        "delivered_status",
        "created_at",
        "updated_at",
    ]
    ordering = ["project_name", "year", "month", "correspondence_type", "sr_no"]

    fieldsets = (
        (
            "Project & Period",
            {
                "fields": (
                    "project_name",
                    "month",
                    "year",
                    "correspondence_type",
                    "sr_no",
                    "description",
                )
            },
        ),
        (
            "Dates & Delivered Status",
            {
                "fields": (
                    "received_date",
                    "deadline_date",
                    "delivered_date",
                    "delivered_status",
                ),
            },
        ),
        (
            "Timestamps",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )
