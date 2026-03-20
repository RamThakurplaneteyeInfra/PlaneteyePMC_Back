from django.contrib import admin

from .models import CashFlow


@admin.register(CashFlow)
class CashFlowAdmin(admin.ModelAdmin):
    list_display = (
        "project_name",
        "month_year",
        "cash_in_monthly_plan",
        "cash_in_monthly_actual",
        "cash_out_monthly_plan",
        "cash_out_monthly_actual",
        "actual_cost_monthly",
        "cash_in_cumulative_actual",
        "cash_out_cumulative_actual",
        "created_at",
    )
    list_filter = ("project_name",)
    search_fields = ("project_name", "month_year")
    ordering = ("project_name", "month_year")
    readonly_fields = (
        "cash_in_cumulative_plan",
        "cash_in_cumulative_actual",
        "cash_out_cumulative_plan",
        "cash_out_cumulative_actual",
        "actual_cost_cumulative",
        "created_at",
    )
