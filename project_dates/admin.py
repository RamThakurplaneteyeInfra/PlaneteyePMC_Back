"""
Django admin registration for the Project Dates app.
"""

from django.contrib import admin

from .eot_models import ProjectEOT
from .models import BGStatus, ProjectBGStatus, ProjectDates


class BGStatusInline(admin.TabularInline):
    model = BGStatus
    extra = 0
    fields = [
        "bg_type",
        "bg_name",
        "due_date",
        "updated_date",
        "remarks",
    ]
    readonly_fields = []


class ProjectEOTInline(admin.TabularInline):
    model = ProjectEOT
    fk_name = "project_dates"
    extra = 0
    fields = [
        "eot_number",
        "extension_days",
        "revised_completion_date",
        "status",
        "is_active",
    ]
    readonly_fields = ["eot_number"]
    show_change_link = True


@admin.register(ProjectDates)
class ProjectDatesAdmin(admin.ModelAdmin):
    list_display = [
        "project",
        "date_type",
        "contractor_name",
        "project_start",
        "contract_finish",
        "forecast_finish",
        "eot_date",
        "created_at",
        "updated_at",
    ]
    list_filter = ["date_type", "created_at"]
    search_fields = ["project__name", "date_type", "contractor_name"]
    readonly_fields = ["created_at", "updated_at"]
    ordering = ["project__name", "date_type", "contractor_name"]
    inlines = [BGStatusInline, ProjectEOTInline]

    fieldsets = (
        ("Project & Type", {"fields": ("project", "date_type", "contractor_name")}),
        (
            "Schedule Dates",
            {
                "fields": ("project_start", "contract_finish", "forecast_finish", "eot_date"),
                "description": (
                    "eot_date is kept in sync with the latest approved ProjectEOT "
                    "revised_completion_date for backward compatibility."
                ),
            },
        ),
        ("Timestamps", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )


@admin.register(ProjectEOT)
class ProjectEOTAdmin(admin.ModelAdmin):
    list_display = [
        "project",
        "eot_number",
        "extension_days",
        "revised_completion_date",
        "status",
        "is_active",
        "approval_date",
        "created_at",
    ]
    list_filter = ["status", "is_active", "created_at"]
    search_fields = ["project__name", "reason", "remarks"]
    readonly_fields = ["created_at", "updated_at", "created_by", "updated_by"]
    ordering = ["project__name", "eot_number"]


@admin.register(BGStatus)
class BGStatusAdmin(admin.ModelAdmin):
    list_display = [
        "bg_name",
        "bg_type",
        "project_date",
        "due_date",
        "updated_date",
        "created_at",
    ]
    list_filter = ["bg_type", "due_date"]
    search_fields = ["bg_name", "project_date__project__name"]
    readonly_fields = ["created_at", "updated_at"]
    ordering = ["project_date__project__name", "bg_type", "id"]


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
