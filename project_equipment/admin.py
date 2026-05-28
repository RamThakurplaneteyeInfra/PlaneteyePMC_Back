"""
Django admin registration for the Project Equipment app.
"""

from django.contrib import admin

from .models.project_equipment import ProjectEquipment


@admin.register(ProjectEquipment)
class ProjectEquipmentAdmin(admin.ModelAdmin):
    """Admin view for Monthly Project Equipment records."""

    list_display = [
        "projectName",
        "equipmentMonth",
        "plannedEquipment",
        "actualEquipment",
        "variance",
        "performancePercentage",
        "created_at",
        "updated_at",
    ]
    list_filter = ["equipmentMonth", "created_at"]
    search_fields = ["projectName", "equipmentMonth"]
    readonly_fields = [
        "variance",
        "performancePercentage",
        "created_at",
        "updated_at",
    ]
    ordering = ["projectName", "equipmentMonth"]

    fieldsets = (
        (
            "Project & Month",
            {"fields": ("projectName", "equipmentMonth")},
        ),
        (
            "Equipment Data",
            {
                "fields": ("plannedEquipment", "actualEquipment", "remarks"),
                "description": (
                    "Enter equipment counts. "
                    "Variance and performance are calculated automatically on save."
                ),
            },
        ),
        (
            "Auto-Calculated KPIs",
            {
                "fields": ("variance", "performancePercentage"),
                "description": "These fields are calculated automatically and cannot be edited directly.",
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
