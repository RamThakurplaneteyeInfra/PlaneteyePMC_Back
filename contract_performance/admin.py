from django.contrib import admin
from .models import ContractPerformance


@admin.register(ContractPerformance)
class ContractPerformanceAdmin(admin.ModelAdmin):
    list_display = (
        "project_name",
        "contract_value",
        "earned_value",
        "earned_value_percentage",
        "actual_billed",
        "actual_billed_percentage",
        "variance",
        "variance_percentage",
        "performance_status",
        "created_by",
        "updated_by",
        "created_at",
    )
    list_filter = ("performance_status", "created_by", "updated_by", "created_at")
    search_fields = ("project_name", "created_by", "updated_by")
    readonly_fields = (
        "earned_value_percentage",
        "actual_billed_percentage",
        "variance",
        "variance_percentage",
        "performance_status",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (None, {
            "fields": ("project_name", "contract_value")
        }),
        ("Performance Metrics", {
            "fields": ("earned_value", "earned_value_percentage", "actual_billed", "actual_billed_percentage")
        }),
        ("Calculated Values", {
            "fields": ("variance", "variance_percentage", "performance_status")
        }),
        ("Tracking", {
            "fields": ("created_by", "updated_by")
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at")
        }),
    )
