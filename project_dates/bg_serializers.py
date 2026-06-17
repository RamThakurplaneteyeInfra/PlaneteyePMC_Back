"""Serializer for optional BG Status dates."""

from rest_framework import serializers

from projects.models import Project

from .bg_status import (
    LEGACY_BG_FIELD_MAP,
    calculate_bg_status,
)
from .models import ProjectBGStatus


def _date_to_str(value):
    return value.isoformat() if value else None


class ProjectBGStatusSerializer(serializers.ModelSerializer):
    project_name = serializers.SerializerMethodField(read_only=True)
    contractor_bg_date = serializers.SerializerMethodField(read_only=True)
    contractor_bg_status = serializers.SerializerMethodField(read_only=True)
    scl_bg_date = serializers.SerializerMethodField(read_only=True)
    scl_bg_status = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = ProjectBGStatus
        fields = [
            "id",
            "project_name",
            "contractor_bg_date",
            "contractor_bg_due_date",
            "contractor_bg_updated_date",
            "contractor_bg_status",
            "scl_bg_date",
            "scl_bg_due_date",
            "scl_bg_updated_date",
            "scl_bg_status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "project_name",
            "contractor_bg_date",
            "contractor_bg_status",
            "scl_bg_date",
            "scl_bg_status",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            "contractor_bg_due_date": {"required": False, "allow_null": True},
            "contractor_bg_updated_date": {"required": False, "allow_null": True},
            "scl_bg_due_date": {"required": False, "allow_null": True},
            "scl_bg_updated_date": {"required": False, "allow_null": True},
        }

    def get_project_name(self, obj) -> str:
        return obj.project.name if obj.project_id else ""

    def get_contractor_bg_date(self, obj) -> str | None:
        return _date_to_str(obj.contractor_bg_updated_date)

    def get_contractor_bg_status(self, obj) -> str:
        return calculate_bg_status(obj.contractor_bg_due_date, obj.contractor_bg_updated_date)

    def get_scl_bg_date(self, obj) -> str | None:
        return _date_to_str(obj.scl_bg_updated_date)

    def get_scl_bg_status(self, obj) -> str:
        return calculate_bg_status(obj.scl_bg_due_date, obj.scl_bg_updated_date)

    def validate(self, attrs):
        return attrs


class ProjectBGStatusWriteSerializer(serializers.Serializer):
    """Upsert BG dates by project name — all fields optional."""

    project_name = serializers.CharField(required=False, allow_blank=True)
    contractor_bg_date = serializers.DateField(required=False, allow_null=True)
    contractor_bg_due_date = serializers.DateField(required=False, allow_null=True)
    contractor_bg_updated_date = serializers.DateField(required=False, allow_null=True)
    scl_bg_date = serializers.DateField(required=False, allow_null=True)
    scl_bg_due_date = serializers.DateField(required=False, allow_null=True)
    scl_bg_updated_date = serializers.DateField(required=False, allow_null=True)

    def validate(self, attrs):
        project_name = (attrs.get("project_name") or "").strip()
        if not project_name and not self.context.get("project"):
            raise serializers.ValidationError(
                {"project_name": "project_name is required."}
            )
        if project_name:
            try:
                attrs["project"] = Project.objects.get(name__iexact=project_name)
            except Project.DoesNotExist:
                raise serializers.ValidationError(
                    {"project_name": f"No project found with name '{project_name}'."}
                )
        elif self.context.get("project"):
            attrs["project"] = self.context["project"]

        for legacy_field, model_field in LEGACY_BG_FIELD_MAP.items():
            if legacy_field in attrs and model_field in attrs:
                if attrs[legacy_field] != attrs[model_field]:
                    raise serializers.ValidationError(
                        {
                            legacy_field: (
                                f"{legacy_field} is a legacy alias for "
                                f"{model_field}; do not send conflicting values."
                            )
                        }
                    )
                attrs.pop(legacy_field)

        for legacy_field, model_field in LEGACY_BG_FIELD_MAP.items():
            if legacy_field in attrs:
                attrs[model_field] = attrs.pop(legacy_field)

        return attrs
