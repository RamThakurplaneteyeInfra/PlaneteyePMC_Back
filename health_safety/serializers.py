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
