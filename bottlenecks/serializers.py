from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers

from projects.models import Project

from .models import Bottleneck

User = get_user_model()


class AssignedUserSerializer(serializers.Serializer):
    """Nested assignee for list/detail responses."""

    id = serializers.IntegerField()
    name = serializers.CharField()


class BottleneckSerializer(serializers.ModelSerializer):
    project_id = serializers.PrimaryKeyRelatedField(
        source="project",
        queryset=Project.objects.all(),
    )
    assigned_to = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(is_active=True),
        required=False,
        allow_null=True,
    )
    assigned_to_detail = serializers.SerializerMethodField()

    class Meta:
        model = Bottleneck
        fields = [
            "id",
            "project_id",
            "type",
            "description",
            "priority",
            "status",
            "assigned_to",
            "assigned_to_detail",
            "target_date",
            "remarks",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "assigned_to_detail",
        ]
        extra_kwargs = {
            "type": {"required": True},
            "description": {"required": True},
            "priority": {"required": True},
            "status": {"required": False},
            "remarks": {"required": False, "allow_blank": True},
        }

    def get_assigned_to_detail(self, obj):
        user = obj.assigned_to
        if not user:
            return None
        name = user.get_full_name().strip() if user.get_full_name() else user.username
        return {"id": user.id, "name": name}

    def to_representation(self, instance):
        data = super().to_representation(instance)
        detail = data.pop("assigned_to_detail", None)
        data["assigned_to"] = detail
        return data

    def to_internal_value(self, data):
        if hasattr(data, "copy"):
            data = data.copy()
        else:
            data = dict(data)
        if "assigned_to" in data and data["assigned_to"] in ("", None):
            data["assigned_to"] = None
        return super().to_internal_value(data)

    def validate_type(self, value):
        valid = {c[0] for c in Bottleneck.TYPE_CHOICES}
        if value not in valid:
            raise serializers.ValidationError(
                f"type must be one of: {', '.join(sorted(valid))}."
            )
        return value

    def validate_priority(self, value):
        valid = {c[0] for c in Bottleneck.PRIORITY_CHOICES}
        if value not in valid:
            raise serializers.ValidationError(
                f"priority must be one of: {', '.join(sorted(valid))}."
            )
        return value

    def validate_status(self, value):
        valid = {c[0] for c in Bottleneck.STATUS_CHOICES}
        if value not in valid:
            raise serializers.ValidationError(
                f"status must be one of: {', '.join(sorted(valid))}."
            )
        return value

    def validate_target_date(self, value):
        if value is None:
            return value

        instance = getattr(self, "instance", None)
        if instance and instance.created_at:
            reference = instance.created_at.date()
        else:
            reference = timezone.localdate()

        if value < reference:
            raise serializers.ValidationError(
                "Target date cannot be earlier than the created date."
            )
        return value
