from django.contrib import admin

from .models import MPRReport


@admin.register(MPRReport)
class MPRReportAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "project",
        "report_year",
        "report_month",
        "version",
        "is_latest",
        "status",
        "generated_at",
        "generated_by",
        "created_at",
    )
    list_filter = ("status", "is_latest", "report_year", "report_month")
    search_fields = ("project__name", "pdf_key", "excel_key")
    readonly_fields = (
        "created_at",
        "updated_at",
        "generated_at",
        "generation_started_at",
        "snapshot_json",
        "pdf_key",
        "pdf_url",
        "excel_key",
        "excel_url",
    )
