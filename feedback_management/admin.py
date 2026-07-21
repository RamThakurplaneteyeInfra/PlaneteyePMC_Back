from django.contrib import admin

from .models import FeedbackAuditLog, ProjectFeedback


@admin.register(ProjectFeedback)
class ProjectFeedbackAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "issue_title",
        "project",
        "status",
        "priority",
        "reported_by",
        "is_active",
        "created_at",
    ]
    list_filter = ["status", "priority", "is_active", "created_at"]
    search_fields = ["issue_title", "issue_description", "project__name"]
    readonly_fields = [
        "attachment_url",
        "attachment_name",
        "attachment_size",
        "attachment_type",
        "attachment_key",
        "created_at",
        "updated_at",
        "resolved_at",
    ]
    raw_id_fields = ["project", "reported_by", "assigned_team_leader"]


@admin.register(FeedbackAuditLog)
class FeedbackAuditLogAdmin(admin.ModelAdmin):
    list_display = ["id", "action", "project", "feedback_id_snapshot", "actor", "created_at"]
    list_filter = ["action", "created_at"]
    search_fields = ["detail", "project__name"]
    readonly_fields = [f.name for f in FeedbackAuditLog._meta.fields]
