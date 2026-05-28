"""
Django admin registration for the Correspondence app.
"""

from django.contrib import admin

from .models.correspondence import Correspondence


@admin.register(Correspondence)
class CorrespondenceAdmin(admin.ModelAdmin):
    """Admin view for Correspondence records."""

    list_display = [
        "projectName",
        "correspondenceReceived",
        "correspondenceDelivered",
        "pendingCorrespondence",
        "deliveryPercentage",
        "created_at",
        "updated_at",
    ]
    list_filter = ["created_at"]
    search_fields = ["projectName"]
    readonly_fields = [
        "pendingCorrespondence",
        "deliveryPercentage",
        "created_at",
        "updated_at",
    ]
    ordering = ["projectName"]

    fieldsets = (
        ("Project", {"fields": ("projectName",)}),
        (
            "Correspondence Counts",
            {
                "fields": (
                    "correspondenceReceived",
                    "correspondenceDelivered",
                ),
            },
        ),
        (
            "Auto-Calculated KPIs",
            {
                "fields": ("pendingCorrespondence", "deliveryPercentage"),
                "description": (
                    "These fields are calculated automatically and cannot be edited."
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
