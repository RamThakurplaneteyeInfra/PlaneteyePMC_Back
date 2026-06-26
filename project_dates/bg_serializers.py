"""Serializers for multi-entry BG Status."""

from rest_framework import serializers

from projects.models import Project

from .bg_status import calculate_bg_status
from .models import BGStatus, ProjectDates


def _date_to_str(value):
    return value.isoformat() if value else None


class BGStatusSerializer(serializers.ModelSerializer):
    """Read serializer — status is calculated dynamically."""

    due_date = serializers.DateField(format="%Y-%m-%d")
    updated_date = serializers.DateField(format="%Y-%m-%d", allow_null=True, required=False)
    status = serializers.SerializerMethodField()

    class Meta:
        model = BGStatus
        fields = [
            "id",
            "bg_type",
            "bg_name",
            "due_date",
            "updated_date",
            "status",
            "remarks",
        ]
        read_only_fields = fields

    def get_status(self, obj) -> str:
        today = self.context.get("today")
        return calculate_bg_status(obj.due_date, obj.updated_date, today=today)


class BGStatusCreateSerializer(serializers.Serializer):
    """Create a new BG entry for a project (does not overwrite existing rows)."""

    bg_type = serializers.ChoiceField(choices=BGStatus.BG_TYPE_CHOICES)
    bg_name = serializers.CharField(max_length=255)
    due_date = serializers.DateField()
    updated_date = serializers.DateField(required=False, allow_null=True)
    remarks = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs):
        project = self.context.get("project")
        if project is None:
            raise serializers.ValidationError(
                {"project": "Project context is required."}
            )

        bg_type = attrs["bg_type"]
        project_date = ProjectDates.objects.filter(
            project_id=project.id,
            date_type=bg_type,
        ).first()
        if project_date is None:
            raise serializers.ValidationError(
                {
                    "bg_type": (
                        f"No {bg_type} project dates record exists for this project. "
                        f"Create the {bg_type} schedule record first."
                    )
                }
            )

        attrs["project_date"] = project_date
        return attrs

    def create(self, validated_data):
        project_date = validated_data.pop("project_date")
        remarks = validated_data.pop("remarks", "")
        return BGStatus.objects.create(
            project_date=project_date,
            remarks=remarks,
            **validated_data,
        )


class BGStatusUpdateSerializer(serializers.ModelSerializer):
    """Partial update for a single BG entry."""

    due_date = serializers.DateField(required=False)
    updated_date = serializers.DateField(required=False, allow_null=True)
    bg_name = serializers.CharField(max_length=255, required=False)
    remarks = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = BGStatus
        fields = [
            "bg_name",
            "due_date",
            "updated_date",
            "remarks",
        ]
