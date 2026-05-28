# Health & Safety Serializers
from decimal import Decimal
from rest_framework import serializers
from .models import HealthSafetyReport

# Constants for incident types
INCIDENT_KEYS = ['fatalities', 'significant', 'major', 'minor', 'near_miss']


class HealthSafetyInputSerializer(serializers.Serializer):
    """
    Serializer for input data - accepts JSON as per requirements
    """
    totalManhours = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0'), required=True)
    incidents = serializers.DictField(
        child=serializers.IntegerField(min_value=0),
        required=True
    )

    def validate_incidents(self, value):
        """
        Validate that all required incident keys are present
        """
        missing_keys = set(INCIDENT_KEYS) - set(value.keys())
        if missing_keys:
            raise serializers.ValidationError(f"Missing required incident keys: {', '.join(missing_keys)}")
        return value


class HealthSafetyReportSerializer(serializers.ModelSerializer):
    """
    Serializer for Health & Safety Report model
    """
    totalIncidents = serializers.IntegerField(source='total_incidents', read_only=True)

    class Meta:
        model = HealthSafetyReport
        fields = [
            'id', 'project_name', 'report_date', 'total_manhours',
            'fatalities', 'significant', 'major', 'minor', 'near_miss',
            'totalIncidents', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class IncidentBreakdownSerializer(serializers.Serializer):
    """Serializer for incident breakdown with counts and percentages"""
    count = serializers.IntegerField()
    percentage = serializers.DecimalField(max_digits=5, decimal_places=2)


class PyramidItemSerializer(serializers.Serializer):
    """Serializer for pyramid visualization data"""
    label = serializers.CharField()
    value = serializers.IntegerField()
    color = serializers.CharField()


class AlertFlagsSerializer(serializers.Serializer):
    """Serializer for alert flags"""
    hasFatality = serializers.BooleanField()
    highNearMiss = serializers.BooleanField()


class HealthSafetyStatusResponseSerializer(serializers.Serializer):
    """
    Complete response serializer for Health & Safety Status API
    Returns all calculated metrics and pyramid data
    """
    summary = serializers.DictField()
    breakdown = serializers.DictField()
    pyramid = PyramidItemSerializer(many=True)
    insights = serializers.ListField(child=serializers.CharField())
    alerts = AlertFlagsSerializer(required=False)
    severityIndex = serializers.DecimalField(max_digits=5, decimal_places=2, required=False)


# =============================================================================
# HSE RECORD SERIALIZER
# Handles input validation and output formatting for HSERecord.
# Uses camelCase field names to match the frontend HSE edit modal directly.
# =============================================================================

from .models import HSERecord  # noqa: E402 — appended after existing imports


class HSERecordSerializer(serializers.ModelSerializer):
    """
    Serializer for the HSERecord model.

    Read-only computed fields exposed for dashboard KPI cards:
      - totalIncidents   : sum of all incident categories
      - ltifr            : Lost Time Injury Frequency Rate
      - incidentRate     : Total incidents per 1,000,000 manhours

    Writable fields (all validated non-negative):
      - projectName, fatalities, significant, major, minor,
        nearMiss, totalManhours, lossOfManhours
    """

    # Computed properties from the model — read-only, never sent by the client
    totalIncidents = serializers.IntegerField(read_only=True)
    ltifr = serializers.FloatField(read_only=True)
    incidentRate = serializers.FloatField(read_only=True)

    class Meta:
        model = HSERecord
        fields = [
            "id",
            "projectName",
            "fatalities",
            "significant",
            "major",
            "minor",
            "nearMiss",
            "totalManhours",
            "lossOfManhours",
            # Computed KPI fields (read-only)
            "totalIncidents",
            "ltifr",
            "incidentRate",
            # Timestamps
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "totalIncidents",
            "ltifr",
            "incidentRate",
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

    def _validate_non_negative_int(self, value: int, field_name: str) -> int:
        """Reusable helper: ensure integer field is >= 0."""
        if value < 0:
            raise serializers.ValidationError(f"{field_name} must be >= 0.")
        return value

    def _validate_non_negative_decimal(self, value, field_name: str):
        """Reusable helper: ensure decimal field is >= 0."""
        if value < 0:
            raise serializers.ValidationError(f"{field_name} must be >= 0.")
        return value

    def validate_fatalities(self, value):
        return self._validate_non_negative_int(value, "fatalities")

    def validate_significant(self, value):
        return self._validate_non_negative_int(value, "significant")

    def validate_major(self, value):
        return self._validate_non_negative_int(value, "major")

    def validate_minor(self, value):
        return self._validate_non_negative_int(value, "minor")

    def validate_nearMiss(self, value):
        return self._validate_non_negative_int(value, "nearMiss")

    def validate_totalManhours(self, value):
        return self._validate_non_negative_decimal(value, "totalManhours")

    def validate_lossOfManhours(self, value):
        return self._validate_non_negative_decimal(value, "lossOfManhours")

    # -------------------------------------------------------------------------
    # Cross-field validation
    # -------------------------------------------------------------------------

    def validate(self, attrs: dict) -> dict:
        """
        Cross-field check: lossOfManhours must not exceed totalManhours.
        Falls back to existing instance values on partial updates.
        """
        instance = self.instance  # None on create, existing object on update

        total_manhours = attrs.get(
            "totalManhours",
            getattr(instance, "totalManhours", 0) if instance else 0,
        )
        loss_of_manhours = attrs.get(
            "lossOfManhours",
            getattr(instance, "lossOfManhours", 0) if instance else 0,
        )

        if loss_of_manhours > total_manhours:
            raise serializers.ValidationError(
                {
                    "lossOfManhours": (
                        f"lossOfManhours ({loss_of_manhours}) cannot exceed "
                        f"totalManhours ({total_manhours})."
                    )
                }
            )

        return attrs
