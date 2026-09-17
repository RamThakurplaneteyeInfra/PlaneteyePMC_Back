"""Serializers for multi-entry BG Status."""

from rest_framework import serializers

from .bg_status import calculate_bg_status
from .models import BGStatus, ProjectDates


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
    """Create a new BG entry for a project schedule row."""

    bg_type = serializers.ChoiceField(choices=BGStatus.BG_TYPE_CHOICES)
    bg_name = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    due_date = serializers.DateField(required=False, allow_null=True)
    updated_date = serializers.DateField(required=False, allow_null=True)
    remarks = serializers.CharField(required=False, allow_blank=True, default="")
    contractor_name = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Deprecated — use contractor_id.",
    )
    contractor_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Required when bg_type=CONTRACTOR and multiple contractors exist.",
    )

    def validate(self, attrs):
        project = self.context.get("project")
        if project is None:
            raise serializers.ValidationError(
                {"project": "Project context is required."}
            )

        bg_type = attrs["bg_type"]
        contractor_name = (attrs.get("contractor_name") or "").strip() or None
        contractor_id = attrs.get("contractor_id")

        if bg_type == ProjectDates.DATE_TYPE_CONTRACTOR:
            contractor_qs = ProjectDates.objects.filter(
                project_id=project.id,
                date_type=ProjectDates.DATE_TYPE_CONTRACTOR,
            )
            if contractor_qs.count() > 1 and not contractor_id and not contractor_name:
                raise serializers.ValidationError(
                    {
                        "contractor_id": (
                            "contractor_id is required when the project has "
                            "multiple contractor schedules."
                        )
                    }
                )

        from .bg_status import get_project_date_for_bg

        project_date = get_project_date_for_bg(
            project, bg_type, contractor_name, contractor_id=contractor_id
        )
        if project_date is None:
            if bg_type == ProjectDates.DATE_TYPE_CONTRACTOR and (contractor_id or contractor_name):
                field = "contractor_id" if contractor_id else "contractor_name"
                label = contractor_id or contractor_name
                raise serializers.ValidationError(
                    {
                        field: (
                            f"No contractor schedule for '{label}' exists "
                            "for this project. Create the contractor schedule first."
                        )
                    }
                )
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
        validated_data.pop("contractor_name", None)
        validated_data.pop("contractor_id", None)
        remarks = validated_data.pop("remarks", "")
        return BGStatus.objects.create(
            project_date=project_date,
            remarks=remarks,
            **validated_data,
        )


class BGStatusUpdateSerializer(serializers.ModelSerializer):
    """Partial update for a single BG entry."""

    due_date = serializers.DateField(required=False, allow_null=True)
    updated_date = serializers.DateField(required=False, allow_null=True)
    bg_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    remarks = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = BGStatus
        fields = [
            "bg_name",
            "due_date",
            "updated_date",
            "remarks",
        ]
