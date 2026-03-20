from django.contrib import admin

from .models import ProjectManpower


@admin.register(ProjectManpower)
class ProjectManpowerAdmin(admin.ModelAdmin):
    list_display = (
        "project_name",
        "month_year",
        "planned_manpower",
        "actual_manpower",
        "working_hours_per_day",
        "working_days_per_month",
        "planned_mh",
        "actual_mh",
        "planned_mh_cumulative",
        "actual_mh_cumulative",
        "created_at",
    )
    list_filter = ("project_name",)
    search_fields = ("project_name", "month_year")
    ordering = ("project_name", "month_year")
    readonly_fields = (
        "planned_mh",
        "actual_mh",
        "planned_mh_cumulative",
        "actual_mh_cumulative",
        "created_at",
    )
