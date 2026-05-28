"""
Planned vs Earned Value Serializer.

Handles input validation and output formatting for PlannedEarnedValue records.

Calculated fields are read-only — always derived by the model's save():
  - variance
  - variancePercentage
  - performancePercentage

Computed properties exposed as read-only output fields:
  - schedulePerformanceIndex  (SPI = EV / PV)
  - performanceStatus         (ahead / on_track / at_risk / behind)

Validation rules:
  - projectName       : required, non-blank string
  - plannedValue      : Decimal >= 0
  - earnedValue       : Decimal >= 0
    (earnedValue > plannedValue is intentionally allowed — ahead of schedule)
"""

from decimal import Decimal

from rest_framework import serializers

from ..models.planned_earned_value import PlannedEarnedValue


class PlannedEarnedValueSerializer(serializers.ModelSerializer):
    """
    Full serializer for PlannedEarnedValue model.

    Read-only fields (auto-calculated by the model on every save):
      - id
      - variance
      - variancePercentage
      - performancePercentage
      - created_at
      - updated_at

    Read-only computed properties (derived at runtime, not stored):
      - schedulePerformanceIndex
      - performanceStatus

    Writable fields:
      - projectName   (required, unique per project)
      - plannedValue  (>= 0)
      - earnedValue   (>= 0; may exceed plannedValue)
    """

    # Expose Python @property fields as read-only serializer fields
    schedulePerformanceIndex = serializers.FloatField(read_only=True)
    performanceStatus = serializers.CharField(read_only=True)

    class Meta:
        model = PlannedEarnedValue
        fields = [
            "id",
            "projectName",
            "plannedValue",
            "earnedValue",
            # Auto-calculated stored fields
            "variance",
            "variancePercentage",
            "performancePercentage",
            # Computed runtime properties
            "schedulePerformanceIndex",
            "performanceStatus",
            # Timestamps
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "variance",
            "variancePercentage",
            "performancePercentage",
            "schedulePerformanceIndex",
            "performanceStatus",
            "created_at",
            "updated_at",
        ]

    # -------------------------------------------------------------------------
    # Field-level validation
    # -------------------------------------------------------------------------

    def validate_projectName(self, value: str) -> str:
        """Strip whitespace and reject blank project names."""
        if not value or not value.strip():
            raise serializers.ValidationError("projectName cannot be blank.")
        return value.strip()

    def validate_plannedValue(self, value: Decimal) -> Decimal:
        """Ensure plannedValue is non-negative."""
        if value < 0:
            raise serializers.ValidationError(
                "plannedValue must be >= 0. Negative planned values are not allowed."
            )
        return value

    def validate_earnedValue(self, value: Decimal) -> Decimal:
        """
        Ensure earnedValue is non-negative.
        Note: earnedValue > plannedValue is intentionally allowed
        (project is ahead of schedule).
        """
        if value < 0:
            raise serializers.ValidationError(
                "earnedValue must be >= 0. Negative earned values are not allowed."
            )
        return value

    # -------------------------------------------------------------------------
    # Cross-field validation
    # -------------------------------------------------------------------------

    def validate(self, attrs: dict) -> dict:
        """
        Cross-field validation.

        No hard constraint between plannedValue and earnedValue —
        earnedValue > plannedValue is valid (ahead of schedule).

        For partial updates, fall back to existing instance values
        so validation is accurate even when only one field is sent.
        """
        instance = self.instance  # None on create, existing object on update

        planned = attrs.get(
            "plannedValue",
            getattr(instance, "plannedValue", Decimal("0")) if instance else Decimal("0"),
        )
        earned = attrs.get(
            "earnedValue",
            getattr(instance, "earnedValue", Decimal("0")) if instance else Decimal("0"),
        )

        # Both must be non-negative (belt-and-suspenders; field validators run first)
        if planned < 0:
            raise serializers.ValidationError(
                {"plannedValue": "plannedValue must be >= 0."}
            )
        if earned < 0:
            raise serializers.ValidationError(
                {"earnedValue": "earnedValue must be >= 0."}
            )

        return attrs
