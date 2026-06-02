"""
Planned vs Earned Value Serializer.

Accepts camelCase (legacy) and snake_case (new) field names on write.
CRUD responses use camelCase for backward compatibility.

Calculated fields (read-only):
  - variance, variancePercentage, performancePercentage
  - schedulePerformanceIndex, spi, performanceStatus
"""

from decimal import Decimal

from rest_framework import serializers

from ..models.planned_earned_value import PlannedEarnedValue


class PlannedEarnedValueSerializer(serializers.ModelSerializer):
    """Full serializer for PlannedEarnedValue monthly records."""

    schedulePerformanceIndex = serializers.FloatField(read_only=True)
    spi = serializers.FloatField(read_only=True)
    performanceStatus = serializers.CharField(read_only=True)

    # snake_case aliases for read (alongside legacy camelCase)
    project_name = serializers.SerializerMethodField()
    planned_value = serializers.DecimalField(
        source="plannedValue",
        max_digits=20,
        decimal_places=4,
        read_only=True,
    )
    earned_value = serializers.DecimalField(
        source="earnedValue",
        max_digits=20,
        decimal_places=4,
        read_only=True,
    )
    performance_percentage = serializers.FloatField(
        source="performancePercentage",
        read_only=True,
    )

    class Meta:
        model = PlannedEarnedValue
        fields = [
            "id",
            # Legacy camelCase (backward compatible)
            "projectName",
            "plannedValue",
            "earnedValue",
            # New monthly / type fields
            "value_type",
            "month",
            "year",
            # snake_case read aliases
            "project_name",
            "planned_value",
            "earned_value",
            "performance_percentage",
            # Auto-calculated
            "variance",
            "variancePercentage",
            "performancePercentage",
            "schedulePerformanceIndex",
            "spi",
            "performanceStatus",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "project_name",
            "planned_value",
            "earned_value",
            "performance_percentage",
            "variance",
            "variancePercentage",
            "performancePercentage",
            "schedulePerformanceIndex",
            "spi",
            "performanceStatus",
            "created_at",
            "updated_at",
        ]
        validators = []

    def get_project_name(self, obj) -> str:
        return obj.projectName

    def to_internal_value(self, data):
        """Normalize snake_case aliases to camelCase model fields."""
        if hasattr(data, "copy"):
            data = data.copy()
        else:
            data = dict(data)

        if "project_name" in data and "projectName" not in data:
            data["projectName"] = data["project_name"]
        if "planned_value" in data and "plannedValue" not in data:
            data["plannedValue"] = data["planned_value"]
        if "earned_value" in data and "earnedValue" not in data:
            data["earnedValue"] = data["earned_value"]

        return super().to_internal_value(data)

    def validate_projectName(self, value: str) -> str:
        if not value or not value.strip():
            raise serializers.ValidationError("projectName cannot be blank.")
        return value.strip()

    def validate_value_type(self, value: str) -> str:
        allowed = {
            PlannedEarnedValue.VALUE_TYPE_SCL,
            PlannedEarnedValue.VALUE_TYPE_CONTRACTOR,
        }
        if value not in allowed:
            raise serializers.ValidationError("value_type must be SCL or CONTRACTOR.")
        return value

    def validate_month(self, value: int) -> int:
        if not (1 <= value <= 12):
            raise serializers.ValidationError("month must be between 1 and 12.")
        return value

    def validate_year(self, value: int) -> int:
        if not (2000 <= value <= 2100):
            raise serializers.ValidationError("year must be between 2000 and 2100.")
        return value

    def validate_plannedValue(self, value: Decimal) -> Decimal:
        if value < 0:
            raise serializers.ValidationError("plannedValue must be >= 0.")
        return value

    def validate_earnedValue(self, value: Decimal) -> Decimal:
        if value < 0:
            raise serializers.ValidationError("earnedValue must be >= 0.")
        return value

    def validate(self, attrs: dict) -> dict:
        instance = self.instance

        planned = attrs.get(
            "plannedValue",
            getattr(instance, "plannedValue", Decimal("0")) if instance else Decimal("0"),
        )
        earned = attrs.get(
            "earnedValue",
            getattr(instance, "earnedValue", Decimal("0")) if instance else Decimal("0"),
        )

        if planned < 0:
            raise serializers.ValidationError({"plannedValue": "plannedValue must be >= 0."})
        if earned < 0:
            raise serializers.ValidationError({"earnedValue": "earnedValue must be >= 0."})

        return attrs
