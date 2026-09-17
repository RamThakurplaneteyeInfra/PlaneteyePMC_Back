from django.contrib import admin

from .models import Contractor


@admin.register(Contractor)
class ContractorAdmin(admin.ModelAdmin):
    list_display = [
        "contractor_name",
        "project",
        "contractor_code",
        "contact_person",
        "phone",
        "status",
        "updated_at",
    ]
    list_filter = ["status", "project"]
    search_fields = ["contractor_name", "contractor_code", "project__name"]
