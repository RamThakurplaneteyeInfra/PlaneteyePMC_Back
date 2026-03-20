from django.contrib import admin
from .models import ProjectProgressStatus


@admin.register(ProjectProgressStatus)
class ProjectProgressStatusAdmin(admin.ModelAdmin):
    list_display = (
        "project_name",
        "progress_month",
        "monthly_plan",
        "cumulative_plan",
        "monthly_actual",
        "cumulative_actual",
        "created_by",
        "updated_by",
        "created_at",
    )
    list_filter = ("project_name", "progress_month", "created_by", "updated_by", "created_at")
    search_fields = ("project_name", "created_by", "updated_by")
    readonly_fields = (
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (None, {
            "fields": ("project_name", "progress_month")
        }),
        ("Planned Progress", {
            "fields": ("monthly_plan", "cumulative_plan")
        }),
        ("Actual Progress", {
            "fields": ("monthly_actual", "cumulative_actual")
        }),
        ("Tracking", {
            "fields": ("created_by", "updated_by")
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at")
        }),
    )
    date_hierarchy = "progress_month"
