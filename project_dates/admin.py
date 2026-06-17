"""
Django admin registration for the Project Dates app.
"""

from django.contrib import admin

from .models import ProjectBGStatus, ProjectDates


@admin.register(ProjectDates)
class ProjectDatesAdmin(admin.ModelAdmin):
    list_display = [
        "project",
        "date_type",
        "project_start",
        "contract_finish",
        "forecast_finish",
        "eot_date",
        "created_at",
        "updated_at",
    ]
    list_filter = ["date_type", "created_at"]
    search_fields = ["project__name", "date_type"]
    readonly_fields = ["created_at", "updated_at"]
    ordering = ["project__name", "date_type"]

    fieldsets = (
        ("Project & Type", {"fields": ("project", "date_type")}),
        (
            "Schedule Dates",
            {
                "fields": ("project_start", "contract_finish", "forecast_finish", "eot_date"),
                "description": (
                    "Business rules: project_start ≤ contract_finish ≤ forecast_finish; "
                    "contract_finish ≤ eot_date."
                ),
            },
        ),
        ("Timestamps", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )


@admin.register(ProjectBGStatus)
class ProjectBGStatusAdmin(admin.ModelAdmin):
    list_display = [
        "project",
        "contractor_bg_due_date",
        "contractor_bg_updated_date",
        "scl_bg_due_date",
        "scl_bg_updated_date",
        "created_at",
        "updated_at",
    ]
    search_fields = ["project__name"]
    readonly_fields = ["created_at", "updated_at"]
    ordering = ["project__name"]
