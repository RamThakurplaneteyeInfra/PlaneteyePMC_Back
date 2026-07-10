"""
Planned vs Actual serializer — SCL and CONTRACTOR monthly records.
"""

from decimal import Decimal

from rest_framework import serializers

from accounts.rbac import normalize_project_name, resolve_project
from contractors.resolvers import (
    contractor_payload,
    resolve_contractor_for_write,
    resolve_project_for_module,
)

from ..models.planned_earned_value import PlannedEarnedValue


class PlannedEarnedValueSerializer(serializers.ModelSerializer):
    project_name = serializers.CharField(max_length=255, trim_whitespace=True)
    projectName = serializers.CharField(source="project_name", read_only=True)
    contractor_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    contractor = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    updated_by_name = serializers.SerializerMethodField()

    class Meta:
        model = PlannedEarnedValue
        fields = [
            "id",
            "project",
            "project_name",
            "projectName",
            "planned_type",
            "contractor_id",
            "contractor",
            "contractor_name",
            "month",
            "year",
            "planned_value",
            "actual_value",
            "collection",
            "difference",
            "achievement_percentage",
            "collection_percentage",
            "variance_percentage",
            "variance_status",
            "reason_for_difference",
            "remarks",
            "created_by",
            "created_by_name",
            "updated_by",
            "updated_by_name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "project",
            "projectName",
            "contractor",
            "contractor_name",
            "difference",
            "achievement_percentage",
            "collection_percentage",
            "variance_percentage",
            "variance_status",
            "created_by",
            "created_by_name",
            "updated_by",
            "updated_by_name",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            "planned_type": {"required": False},
            "reason_for_difference": {"required": False, "allow_blank": True},
            "remarks": {"required": False, "allow_blank": True},
        }

    def get_contractor(self, obj):
        return contractor_payload(obj.contractor)

    def _display_user(self, user):
        if not user:
            return None
        return user.get_full_name() or user.username

    def get_created_by_name(self, obj):
        return self._display_user(obj.created_by)

    def get_updated_by_name(self, obj):
        return self._display_user(obj.updated_by)

    def to_internal_value(self, data):
        if hasattr(data, "copy"):
            data = data.copy()
        else:
            data = dict(data)

        if "projectName" in data and "project_name" not in data:
            data["project_name"] = data["projectName"]
        if "plannedType" in data and "planned_type" not in data:
            data["planned_type"] = data["plannedType"]
        if "value_type" in data and "planned_type" not in data:
            data["planned_type"] = data["value_type"]
        if "earned_value" in data and "actual_value" not in data:
            data["actual_value"] = data["earned_value"]
        if "earnedValue" in data and "actual_value" not in data:
            data["actual_value"] = data["earnedValue"]
        if "plannedValue" in data and "planned_value" not in data:
            data["planned_value"] = data["plannedValue"]
        if "planned_type" in data and data["planned_type"]:
            data["planned_type"] = str(data["planned_type"]).strip().upper()

        return super().to_internal_value(data)

    def validate_project_name(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("project_name cannot be blank.")
        project = resolve_project(normalize_project_name(value))
        if project is None:
            raise serializers.ValidationError("Project not found.")
        return project.name

    def validate_planned_type(self, value: str) -> str:
        value = (value or PlannedEarnedValue.TYPE_SCL).strip().upper()
        if value not in {
            PlannedEarnedValue.TYPE_SCL,
            PlannedEarnedValue.TYPE_CONTRACTOR,
        }:
            raise serializers.ValidationError(
                "planned_type must be SCL or CONTRACTOR."
            )
        return value

    def validate_month(self, value: int) -> int:
        if not (1 <= value <= 12):
            raise serializers.ValidationError("month must be between 1 and 12.")
        return value

    def validate_year(self, value: int) -> int:
        if not (2000 <= value <= 2100):
            raise serializers.ValidationError("year must be between 2000 and 2100.")
        return value

    def validate_planned_value(self, value: Decimal) -> Decimal:
        if value < 0:
            raise serializers.ValidationError("planned_value must be >= 0.")
        return value

    def validate_actual_value(self, value: Decimal) -> Decimal:
        if value < 0:
            raise serializers.ValidationError("actual_value must be >= 0.")
        return value

    def validate_collection(self, value: Decimal) -> Decimal:
        if value < 0:
            raise serializers.ValidationError("collection must be >= 0.")
        return value

    def validate(self, attrs):
        instance = self.instance
        planned_type = attrs.get(
            "planned_type",
            getattr(instance, "planned_type", PlannedEarnedValue.TYPE_SCL)
            if instance
            else PlannedEarnedValue.TYPE_SCL,
        )
        attrs["planned_type"] = planned_type

        project_name = attrs.get(
            "project_name",
            getattr(instance, "project_name", None) if instance else None,
        )
        project = resolve_project_for_module(project_name) if project_name else None
        attrs["_resolved_project"] = project

        contractor_id = attrs.pop("contractor_id", serializers.empty)
        if contractor_id is serializers.empty:
            contractor_id = None if not instance else instance.contractor_id

        if planned_type == PlannedEarnedValue.TYPE_SCL:
            attrs["contractor"] = None
            attrs["contractor_name"] = None
        else:
            contractor = resolve_contractor_for_write(
                project,
                contractor_id=contractor_id,
                contractor_name=attrs.get("contractor_name")
                or (instance.contractor_name if instance else None),
            )
            attrs["contractor"] = contractor
            attrs["contractor_name"] = contractor.contractor_name if contractor else None

        planned = attrs.get(
            "planned_value",
            getattr(instance, "planned_value", Decimal("0")) if instance else Decimal("0"),
        )
        actual = attrs.get(
            "actual_value",
            getattr(instance, "actual_value", Decimal("0")) if instance else Decimal("0"),
        )
        reason = attrs.get(
            "reason_for_difference",
            getattr(instance, "reason_for_difference", "") if instance else "",
        )
        if Decimal(planned) - Decimal(actual) > 0 and not str(reason or "").strip():
            raise serializers.ValidationError(
                {
                    "reason_for_difference": (
                        "reason_for_difference is required when difference > 0."
                    )
                }
            )
        return attrs

    def create(self, validated_data):
        project = validated_data.pop("_resolved_project", None)
        validated_data["project"] = project
        if project:
            validated_data["project_name"] = project.name
        request = self.context.get("request")
        if request and request.user and request.user.is_authenticated:
            validated_data.setdefault("created_by", request.user)
            validated_data.setdefault("updated_by", request.user)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        project = validated_data.pop("_resolved_project", None)
        if project is not None:
            validated_data["project"] = project
            validated_data["project_name"] = project.name
        request = self.context.get("request")
        if request and request.user and request.user.is_authenticated:
            validated_data["updated_by"] = request.user
        return super().update(instance, validated_data)


PlannedVsActualSerializer = PlannedEarnedValueSerializer
