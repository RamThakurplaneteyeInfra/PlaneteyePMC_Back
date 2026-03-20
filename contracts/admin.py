from django.contrib import admin

from .models import Contract


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = (
        "project_name",
        "original_contract_value",
        "approved_vo",
        "pending_vo",
        "revised_contract_value",
        "approved_vo_percentage",
        "status",
        "created_by",
        "approved_by",
        "created_at",
    )
    list_filter = ("status", "created_at")
    search_fields = ("project_name", "created_by", "approved_by")
    ordering = ("-created_at",)

# Register your models here.
