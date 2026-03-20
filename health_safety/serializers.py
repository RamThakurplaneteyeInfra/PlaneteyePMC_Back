# Health & Safety Serializers
from rest_framework import serializers
from .models import HealthSafetyReport


class HealthSafetyInputSerializer(serializers.Serializer):
    """
    Serializer for input data - accepts JSON as per requirements
    """
    totalManhours = serializers.FloatField(min_value=0, required=True)
    incidents = serializers.DictField(
        child=serializers.IntegerField(min_value=0),
        required=True
    )


class HealthSafetyReportSerializer(serializers.ModelSerializer):
    """
    Serializer for Health & Safety Report model
    """
    totalIncidents = serializers.ReadOnlyField()
    
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
    percentage = serializers.FloatField()


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
    severityIndex = serializers.FloatField(required=False)
