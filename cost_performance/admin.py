from django.contrib import admin

from .models import ProjectCostPerformance


@admin.register(ProjectCostPerformance)
class ProjectCostPerformanceAdmin(admin.ModelAdmin):
    list_display = (
        "project_name",
        "month_year",
        "bcws",
        "bcwp",
        "acwp",
        "fcst",
        "eac",
        "cv",
        "sv",
        "cpi",
        "vac",
        "created_at",
    )
    list_filter = ("project_name",)
    search_fields = ("project_name", "month_year")
    readonly_fields = ("eac", "cv", "sv", "cpi", "vac", "created_at")
