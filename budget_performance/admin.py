from django.contrib import admin

from .models import BudgetCostPerformance


@admin.register(BudgetCostPerformance)
class BudgetCostPerformanceAdmin(admin.ModelAdmin):
    list_display = (
        "project_name",
        "bac",
        "bcwp",
        "acwp",
        "cpi",
        "eac",
        "etg",
        "vac",
        "cv",
        "created_at",
    )
    list_filter = ("created_at",)
    search_fields = ("project_name",)
    readonly_fields = (
        "cpi",
        "eac",
        "etg",
        "vac",
        "cv",
        "created_at",
    )
    ordering = ("-created_at",)
