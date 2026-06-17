"""
Django admin registration for the Project Quality Status app.
"""

from django.contrib import admin

from .models.frequency_chart import FrequencyChartEntry, TestFrequencyMaster
from .models.project_quality_status import ProjectQualityStatus


@admin.register(TestFrequencyMaster)
class TestFrequencyMasterAdmin(admin.ModelAdmin):
    list_display = [
        "item_description",
        "type_of_test",
        "unit",
        "frequency_display",
        "projectName",
        "is_archived",
    ]
    list_filter = ["is_archived", "unit", "projectName"]
    search_fields = ["item_description", "type_of_test", "projectName"]


@admin.register(FrequencyChartEntry)
class FrequencyChartEntryAdmin(admin.ModelAdmin):
    list_display = [
        "projectName",
        "month",
        "year",
        "sr_no",
        "item_description",
        "type_of_test",
        "total_qty_display",
        "remarks",
        "is_archived",
    ]
    list_filter = ["year", "month", "is_archived", "type_of_test"]
    search_fields = ["projectName", "item_description", "type_of_test", "contractor_name"]
    autocomplete_fields = ["frequency_master"]

    @admin.display(description="Total Qty")
    def total_qty_display(self, obj):
        return float(obj.qty_previous_bill or 0) + float(obj.qty_this_bill or 0)


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
