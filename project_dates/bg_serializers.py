"""Serializer for optional BG Status dates."""

from rest_framework import serializers

from projects.models import Project

from .models import ProjectBGStatus


class ProjectBGStatusSerializer(serializers.ModelSerializer):
    project_name = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = ProjectBGStatus
        fields = [
            "id",
            "project_name",
            "contractor_bg_date",
            "scl_bg_date",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "project_name", "created_at", "updated_at"]
        extra_kwargs = {
            "contractor_bg_date": {"required": False, "allow_null": True},
            "scl_bg_date": {"required": False, "allow_null": True},
        }

    def get_project_name(self, obj) -> str:
        return obj.project.name if obj.project_id else ""

    def validate(self, attrs):
        return attrs


class ProjectBGStatusWriteSerializer(serializers.Serializer):
    """Upsert BG dates by project name — all fields optional."""

    project_name = serializers.CharField(required=False, allow_blank=True)
    contractor_bg_date = serializers.DateField(required=False, allow_null=True)
    scl_bg_date = serializers.DateField(required=False, allow_null=True)

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
        return attrs
