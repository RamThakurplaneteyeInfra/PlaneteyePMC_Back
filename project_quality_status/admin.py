"""
Django admin registration for the Project Quality Status app.
"""

from django.contrib import admin

from .models.project_quality_status import ProjectQualityStatus


@admin.register(ProjectQualityStatus)
class ProjectQualityStatusAdmin(admin.ModelAdmin):
    """Admin view for monthly Project Quality Status records."""

    list_display = [
        "projectName",
        "month",
        "year",
        "tests_required",
        "tests_conducted",
        "tests_passed",
        "tests_failed",
        "created_at",
        "updated_at",
    ]
    list_filter = ["year", "month", "created_at"]
    search_fields = ["projectName"]
    readonly_fields = ["created_at", "updated_at"]
    ordering = ["projectName", "year", "month"]

    fieldsets = (
        ("Project & Period", {"fields": ("projectName", "month", "year")}),
        (
            "Test Counts",
            {
                "fields": (
                    "tests_required",
                    "tests_conducted",
                    "tests_passed",
                    "tests_failed",
                ),
            },
        ),
        (
            "Timestamps",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )
