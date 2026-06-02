"""
Drawing Summary Serializer.

Writable: project_name (→ Project FK), month, year,
          submitted_drawings, approved_drawings

Computed (never stored): variance, approval_rate
Legacy read aliases: projectName, totalSubmitted, totalApproved, approvalPercentage
"""

from rest_framework import serializers

from projects.models import Project
from ..models.drawing import DrawingSummary
from .drawing_metrics import (
    compute_approval_rate,
    compute_variance,
    metrics_from_record,
)


class DrawingSerializer(serializers.ModelSerializer):
    """Serializer for monthly DrawingSummary records."""

    project_name = serializers.SerializerMethodField()
    variance = serializers.SerializerMethodField()
    approval_rate = serializers.SerializerMethodField()

    # Legacy aliases (read-only)
    projectName = serializers.SerializerMethodField()
    totalSubmitted = serializers.IntegerField(source="submitted_drawings", read_only=True)
    totalApproved = serializers.IntegerField(source="approved_drawings", read_only=True)
    approvalPercentage = serializers.SerializerMethodField()

    class Meta:
        model = DrawingSummary
        fields = [
            "id",
            "project_name",
            "projectName",
            "month",
            "year",
            "submitted_drawings",
            "approved_drawings",
            "variance",
            "approval_rate",
            "totalSubmitted",
            "totalApproved",
            "approvalPercentage",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "project_name",
            "projectName",
            "variance",
            "approval_rate",
            "totalSubmitted",
            "totalApproved",
            "approvalPercentage",
            "created_at",
            "updated_at",
        ]
        validators = []

    def get_project_name(self, obj) -> str:
        return obj.project_name

    def get_projectName(self, obj) -> str:
        return obj.project_name

    def get_variance(self, obj) -> int:
        return compute_variance(obj.submitted_drawings, obj.approved_drawings)

    def get_approval_rate(self, obj) -> float:
        return compute_approval_rate(obj.approved_drawings, obj.submitted_drawings)

    def get_approvalPercentage(self, obj) -> float:
        return self.get_approval_rate(obj)

    def to_internal_value(self, data):
        if hasattr(data, "copy"):
            data = data.copy()
        else:
            data = dict(data)

        if "_project_name" in data:
            data["_project_name"] = str(data.get("_project_name", "")).strip()
        elif "project_name" in data:
            data["_project_name"] = str(data.get("project_name", "")).strip()
        elif "projectName" in data:
            data["_project_name"] = str(data.get("projectName", "")).strip()

        if "totalSubmitted" in data and "submitted_drawings" not in data:
            data["submitted_drawings"] = data["totalSubmitted"]

        if "totalApproved" in data and "approved_drawings" not in data:
            data["approved_drawings"] = data["totalApproved"]

        ret = super().to_internal_value(data)
        ret["_project_name"] = data.get("_project_name", "")
        return ret

    def validate_month(self, value: int) -> int:
        if not (1 <= value <= 12):
            raise serializers.ValidationError("month must be between 1 and 12.")
        return value

    def validate_year(self, value: int) -> int:
        if not (2000 <= value <= 2100):
            raise serializers.ValidationError("year must be between 2000 and 2100.")
        return value

    def _validate_non_negative(self, value: int, field_name: str) -> int:
        if value < 0:
            raise serializers.ValidationError(f"{field_name} must be >= 0.")
        return value

    def validate_submitted_drawings(self, value):
        return self._validate_non_negative(value, "submitted_drawings")

    def validate_approved_drawings(self, value):
        return self._validate_non_negative(value, "approved_drawings")

    def validate(self, attrs: dict) -> dict:
        instance = self.instance

        project_name = attrs.pop("_project_name", "").strip()
        if not project_name:
            if instance is not None:
                attrs["project"] = instance.project
            else:
                raise serializers.ValidationError(
                    {"project_name": "project_name is required."}
                )
        else:
            try:
                project = Project.objects.get(name__iexact=project_name)
            except Project.DoesNotExist:
                raise serializers.ValidationError(
                    {"project_name": f"No project found with name '{project_name}'."}
                )
            attrs["project"] = project

        submitted = attrs.get(
            "submitted_drawings",
            getattr(instance, "submitted_drawings", 0) if instance else 0,
        )
        approved = attrs.get(
            "approved_drawings",
            getattr(instance, "approved_drawings", 0) if instance else 0,
        )

        if approved > submitted:
            raise serializers.ValidationError(
                {
                    "approved_drawings": (
                        f"approved_drawings ({approved}) cannot be greater than "
                        f"submitted_drawings ({submitted})."
                    )
                }
            )

        return attrs

    def create(self, validated_data):
        validated_data.pop("_project_name", None)
        return DrawingSummary.objects.create(**validated_data)

    def update(self, instance, validated_data):
        validated_data.pop("_project_name", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance
