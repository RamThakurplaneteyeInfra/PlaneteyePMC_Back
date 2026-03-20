from django.contrib import admin

from .models import ProjectEquipment


@admin.register(ProjectEquipment)
class ProjectEquipmentAdmin(admin.ModelAdmin):
    list_display = (
        "project_name",
        "month",
        "planned_equipment",
        "actual_equipment",
        "planned_cumulative",
        "actual_cumulative",
        "created_at",
    )
    list_filter = ("project_name", "month")
    search_fields = ("project_name",)
    ordering = ("project_name", "month")
    readonly_fields = ("planned_cumulative", "actual_cumulative", "created_at")
