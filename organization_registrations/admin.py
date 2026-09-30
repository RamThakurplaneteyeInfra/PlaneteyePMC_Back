from django.contrib import admin
from django.contrib import messages

from .models import OrganizationRegistration
from .notifications import attempt_organization_registration_notification


@admin.action(description="Retry pending or failed notification emails")
def retry_registration_notifications(modeladmin, request, queryset):
    sent_count = 0
    failed_count = 0
    retryable = queryset.filter(
        notification_status__in=[
            OrganizationRegistration.NOTIFICATION_PENDING,
            OrganizationRegistration.NOTIFICATION_FAILED,
        ]
    )
    for registration in retryable.iterator():
        if attempt_organization_registration_notification(registration):
            sent_count += 1
        else:
            failed_count += 1

    if sent_count:
        modeladmin.message_user(
            request,
            f"Notification email sent for {sent_count} registration(s).",
            messages.SUCCESS,
        )
    if failed_count:
        modeladmin.message_user(
            request,
            f"Notification email failed for {failed_count} registration(s); they remain retryable.",
            messages.ERROR,
        )


@admin.register(OrganizationRegistration)
class OrganizationRegistrationAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "display_name",
        "legal_name",
        "official_email",
        "admin_email",
        "status",
        "notification_status",
        "submitted_at",
    ]
    list_filter = ["status", "notification_status", "submitted_at", "city"]
    actions = [retry_registration_notifications]
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
        "notification_status",
        "submitted_at",
    ]
    fields = readonly_fields + ["status"]
