from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from accounts.utils import get_user_role
from projects.models import Project
from services.s3_feedback_attachments import validate_attachment

from .models import ProjectFeedback


def _user_brief(user):
    if not user:
        return None
    return {
        "id": user.id,
        "username": user.username,
        "role": get_user_role(user),
    }


class ProjectFeedbackSerializer(serializers.ModelSerializer):
    project = serializers.SerializerMethodField()
    attachment = serializers.SerializerMethodField()
    reported_by = serializers.SerializerMethodField()
    assigned_team_leader = serializers.SerializerMethodField()

    class Meta:
        model = ProjectFeedback
        fields = [
            "id",
            "project",
            "issue_title",
            "issue_description",
            "priority",
            "status",
            "attachment",
            "remarks",
            "reported_by",
            "assigned_team_leader",
            "created_at",
            "updated_at",
            "resolved_at",
            "is_active",
        ]
        read_only_fields = fields

    def get_project(self, obj):
        return {"id": obj.project_id, "name": obj.project.name}

    def get_attachment(self, obj):
        if not obj.attachment_url:
            return None
        return {
            "url": obj.attachment_url,
            "name": obj.attachment_name,
            "type": obj.attachment_type,
            "size": obj.attachment_size,
        }

    def get_reported_by(self, obj):
        return _user_brief(obj.reported_by)

    def get_assigned_team_leader(self, obj):
        return _user_brief(obj.assigned_team_leader)


class FeedbackCreateSerializer(serializers.Serializer):
    project = serializers.PrimaryKeyRelatedField(queryset=Project.objects.all())
    issue_title = serializers.CharField(max_length=255)
    issue_description = serializers.CharField()
    priority = serializers.ChoiceField(
        choices=[c[0] for c in ProjectFeedback.PRIORITY_CHOICES],
        default=ProjectFeedback.PRIORITY_MEDIUM,
    )
    attachment = serializers.FileField(required=False, allow_null=True)

    def validate_issue_title(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("issue_title is required.")
        return value

    def validate_issue_description(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("issue_description is required.")
        return value

    def validate_attachment(self, value):
        if value in (None, ""):
            return None
        try:
            validate_attachment(value)
        except DjangoValidationError as exc:
            messages = getattr(exc, "messages", None) or [str(exc)]
            raise serializers.ValidationError(messages[0])
        return value


class FeedbackUpdateSerializer(serializers.Serializer):
    issue_title = serializers.CharField(max_length=255, required=False)
    issue_description = serializers.CharField(required=False)
    priority = serializers.ChoiceField(
        choices=[c[0] for c in ProjectFeedback.PRIORITY_CHOICES],
        required=False,
    )
    status = serializers.ChoiceField(
        choices=[c[0] for c in ProjectFeedback.STATUS_CHOICES],
        required=False,
    )
    remarks = serializers.CharField(required=False, allow_blank=True)
    attachment = serializers.FileField(required=False, allow_null=True)
    is_active = serializers.BooleanField(required=False)

    def validate_issue_title(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("issue_title cannot be blank.")
        return value

    def validate_attachment(self, value):
        if value in (None, ""):
            return None
        try:
            validate_attachment(value)
        except DjangoValidationError as exc:
            messages = getattr(exc, "messages", None) or [str(exc)]
            raise serializers.ValidationError(messages[0])
        return value


class FeedbackStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=[c[0] for c in ProjectFeedback.STATUS_CHOICES]
    )
