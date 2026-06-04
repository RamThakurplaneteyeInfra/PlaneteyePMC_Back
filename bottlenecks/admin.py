from django.contrib import admin

from .models import Bottleneck


@admin.register(Bottleneck)
class BottleneckAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "project",
        "type",
        "priority",
        "status",
        "assigned_to",
        "target_date",
        "created_at",
    )
    list_filter = ("type", "status", "priority", "project")
    search_fields = ("description", "remarks", "project__name")
    raw_id_fields = ("project", "assigned_to", "created_by", "updated_by")
    readonly_fields = ("created_at", "updated_at")
