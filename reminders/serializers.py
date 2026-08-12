from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers

from accounts.rbac import user_has_project_access
from accounts.rbac_checks import assert_project_writable
from projects.models import Project

from .models import Reminder

User = get_user_model()


class UserBriefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    full_name = serializers.CharField(allow_blank=True)


def _user_brief(user) -> dict | None:
    if user is None:
        return None
    full = f"{user.first_name or ''} {user.last_name or ''}".strip()
    return {
        "id": user.id,
        "username": user.username,
        "full_name": full or user.username,
    }


class ReminderSerializer(serializers.ModelSerializer):
    project_id = serializers.PrimaryKeyRelatedField(
        source="project",
        queryset=Project.objects.all(),
    )
    project_name = serializers.CharField(source="project.name", read_only=True)
    assigned_to_id = serializers.PrimaryKeyRelatedField(
        source="assigned_to",
        queryset=User.objects.filter(is_active=True),
    )
    assigned_to = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()
    effective_due_at = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()

    class Meta:
        model = Reminder
        fields = [
            "id",
            "project_id",
            "project_name",
            "title",
            "description",
            "due_at",
            "effective_due_at",
            "is_overdue",
            "assigned_to_id",
            "assigned_to",
            "created_by",
            "status",
            "snoozed_until",
            "completed_at",
            "dismissed_at",
            "notified_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "project_name",
            "assigned_to",
            "created_by",
            "effective_due_at",
            "is_overdue",
            "status",
            "snoozed_until",
            "completed_at",
            "dismissed_at",
            "notified_at",
            "created_at",
            "updated_at",
        ]

    def get_assigned_to(self, obj):
        return _user_brief(obj.assigned_to)

    def get_created_by(self, obj):
        return _user_brief(obj.created_by)

    def get_effective_due_at(self, obj):
        due = obj.effective_due_at
        return due.isoformat() if due else None

    def get_is_overdue(self, obj):
        if obj.status != Reminder.STATUS_PENDING:
            return False
        due = obj.effective_due_at
        return bool(due and due < timezone.now())

    def validate_project_id(self, project: Project):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            raise serializers.ValidationError("Authentication required.")
        if not user_has_project_access(user, project):
            raise serializers.ValidationError("You do not have access to this project.")
        assert_project_writable(project)
        return project

    def validate_due_at(self, value):
        if value is None:
            raise serializers.ValidationError("due_at is required.")
        return value

    def validate(self, attrs):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        project = attrs.get("project") or getattr(self.instance, "project", None)
        assignee = attrs.get("assigned_to") or getattr(
            self.instance, "assigned_to", None
        )
        if project is not None and assignee is not None:
            if not user_has_project_access(assignee, project):
                raise serializers.ValidationError(
                    {
                        "assigned_to_id": (
                            "Assignee must have access to the selected project."
                        )
                    }
                )
        if project is not None and user is not None:
            assert_project_writable(project)
        title = attrs.get("title", getattr(self.instance, "title", None))
        if title is not None and not str(title).strip():
            raise serializers.ValidationError({"title": "Title cannot be blank."})
        if "title" in attrs:
            attrs["title"] = str(attrs["title"]).strip()
        if "description" in attrs and attrs["description"] is not None:
            attrs["description"] = str(attrs["description"]).strip()
        return attrs

    def create(self, validated_data):
        request = self.context["request"]
        return Reminder.objects.create(
            created_by=request.user,
            **validated_data,
        )


class ReminderSnoozeSerializer(serializers.Serializer):
    """Snooze by absolute datetime or relative minutes (default 30)."""

    snooze_until = serializers.DateTimeField(required=False)
    minutes = serializers.IntegerField(required=False, min_value=1, max_value=60 * 24 * 30)

    def validate(self, attrs):
        until = attrs.get("snooze_until")
        minutes = attrs.get("minutes")
        if until is None and minutes is None:
            minutes = 30
            attrs["minutes"] = minutes
        if until is None:
            attrs["snooze_until"] = timezone.now() + timedelta(minutes=int(minutes))
        if attrs["snooze_until"] <= timezone.now():
            raise serializers.ValidationError(
                {"snooze_until": "Snooze target must be in the future."}
            )
        return attrs
