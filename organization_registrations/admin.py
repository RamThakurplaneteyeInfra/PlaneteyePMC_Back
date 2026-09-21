from django.contrib import admin

from .models import OrganizationRegistration


@admin.register(OrganizationRegistration)
class OrganizationRegistrationAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "display_name",
        "legal_name",
        "official_email",
        "admin_email",
        "status",
        "submitted_at",
    ]
    list_filter = ["status", "submitted_at", "city"]
    search_fields = [
        "legal_name",
        "display_name",
        "official_email",
        "admin_email",
        "admin_name",
        "city",
    ]
    readonly_fields = [
        "legal_name",
        "display_name",
        "office_address",
        "city",
        "pin",
        "phone",
        "official_email",
        "admin_name",
        "admin_email",
        "logo",
        "logo_original_name",
        "logo_s3_key",
        "logo_s3_url",
        "submitted_at",
    ]
    fields = readonly_fields + ["status"]
