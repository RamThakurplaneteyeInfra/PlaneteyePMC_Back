"""
Correspondence Status Serializer.

Writable: project_name (→ Project FK), month, year, correspondence_type,
          correspondence_received, correspondence_delivered

Computed (never stored): pending_correspondence, delivery_efficiency
Legacy read aliases: projectName, correspondenceReceived, correspondenceDelivered,
                     pendingCorrespondence, deliveryPercentage
"""

from rest_framework import serializers

from projects.models import Project
from ..models.correspondence import CorrespondenceStatus
from .correspondence_metrics import (
    compute_delivery_efficiency,
    compute_pending_correspondence,
)


class CorrespondenceSerializer(serializers.ModelSerializer):
    """Serializer for monthly CorrespondenceStatus records."""

    project_name = serializers.SerializerMethodField()
    pending_correspondence = serializers.SerializerMethodField()
    delivery_efficiency = serializers.SerializerMethodField()

    # Legacy aliases (read-only)
    projectName = serializers.SerializerMethodField()
    correspondenceReceived = serializers.IntegerField(
        source="correspondence_received", read_only=True
    )
    correspondenceDelivered = serializers.IntegerField(
        source="correspondence_delivered", read_only=True
    )
    pendingCorrespondence = serializers.SerializerMethodField()
    deliveryPercentage = serializers.SerializerMethodField()

    class Meta:
        model = CorrespondenceStatus
        fields = [
            "id",
            "project_name",
            "projectName",
            "month",
            "year",
            "correspondence_type",
            "correspondence_received",
            "correspondence_delivered",
            "pending_correspondence",
            "delivery_efficiency",
            "correspondenceReceived",
            "correspondenceDelivered",
            "pendingCorrespondence",
            "deliveryPercentage",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "project_name",
            "projectName",
            "pending_correspondence",
            "delivery_efficiency",
            "correspondenceReceived",
            "correspondenceDelivered",
            "pendingCorrespondence",
            "deliveryPercentage",
            "created_at",
            "updated_at",
        ]
        validators = []

    def get_project_name(self, obj) -> str:
        return obj.project_name

    def get_projectName(self, obj) -> str:
        return obj.project_name

    def get_pending_correspondence(self, obj) -> int:
        return compute_pending_correspondence(
            obj.correspondence_received, obj.correspondence_delivered
        )

    def get_delivery_efficiency(self, obj) -> float:
        return compute_delivery_efficiency(
            obj.correspondence_delivered, obj.correspondence_received
        )

    def get_pendingCorrespondence(self, obj) -> int:
        return self.get_pending_correspondence(obj)

    def get_deliveryPercentage(self, obj) -> float:
        return self.get_delivery_efficiency(obj)

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

        if "correspondenceReceived" in data and "correspondence_received" not in data:
            data["correspondence_received"] = data["correspondenceReceived"]
        if "correspondenceDelivered" in data and "correspondence_delivered" not in data:
            data["correspondence_delivered"] = data["correspondenceDelivered"]

        if "correspondence_type" in data and isinstance(data["correspondence_type"], str):
            data["correspondence_type"] = data["correspondence_type"].upper()

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

    def validate_correspondence_type(self, value: str) -> str:
        allowed = {
            CorrespondenceStatus.TYPE_CLIENT,
            CorrespondenceStatus.TYPE_CONTRACTOR,
        }
        value = value.upper()
        if value not in allowed:
            raise serializers.ValidationError(
                "correspondence_type must be CLIENT or CONTRACTOR."
            )
        return value

    def _validate_non_negative(self, value: int, field_name: str) -> int:
        if value < 0:
            raise serializers.ValidationError(f"{field_name} must be >= 0.")
        return value

    def validate_correspondence_received(self, value):
        return self._validate_non_negative(value, "correspondence_received")

    def validate_correspondence_delivered(self, value):
        return self._validate_non_negative(value, "correspondence_delivered")

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

        return attrs

    def create(self, validated_data):
        validated_data.pop("_project_name", None)
        return CorrespondenceStatus.objects.create(**validated_data)

    def update(self, instance, validated_data):
        validated_data.pop("_project_name", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance
