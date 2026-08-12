from django.contrib import admin

from .models import Reminder


@admin.register(Reminder)
class ReminderAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "project",
        "assigned_to",
        "due_at",
        "status",
        "notified_at",
        "created_at",
    )
    list_filter = ("status", "due_at")
    search_fields = ("title", "description", "project__name", "assigned_to__username")
    raw_id_fields = ("project", "assigned_to", "created_by")
    readonly_fields = ("notified_at", "completed_at", "dismissed_at", "created_at", "updated_at")
