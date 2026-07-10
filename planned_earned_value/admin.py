from django.contrib import admin

from .models.planned_earned_value import PlannedEarnedValue


@admin.register(PlannedEarnedValue)
class PlannedEarnedValueAdmin(admin.ModelAdmin):
    list_display = [
        "project_name",
        "planned_type",
        "contractor_name",
        "month",
        "year",
        "planned_value",
        "actual_value",
        "collection",
        "difference",
        "variance_status",
        "updated_at",
    ]
    list_filter = ["planned_type", "year", "month", "variance_status"]
    search_fields = [
        "project_name",
        "contractor_name",
        "reason_for_difference",
        "remarks",
    ]
    readonly_fields = [
        "difference",
        "achievement_percentage",
        "collection_percentage",
        "variance_percentage",
        "variance_status",
        "created_at",
        "updated_at",
    ]
    ordering = ["project_name", "year", "month", "planned_type"]
