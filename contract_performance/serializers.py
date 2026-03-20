from decimal import Decimal
from rest_framework import serializers
from .models import ContractPerformance


class ContractPerformanceSerializer(serializers.ModelSerializer):
    """
    Serializer for Contract Performance.
    
    Notes:
    - All calculated fields (percentages, variance, performance_status) are read-only
    - All monetary fields use DecimalField for precision
    - Validation ensures non-negative values for input fields
    - variance and variance_percentage can be negative (when actual_billed > earned_value)
    """
    
    performance_status_display = serializers.CharField(source='get_performance_status_display', read_only=True)
    
    class Meta:
        model = ContractPerformance
        fields = [
            "id",
            "project_name",
            "contract_value",
            "earned_value",
            "earned_value_percentage",
            "actual_billed",
            "actual_billed_percentage",
            "variance",
            "variance_percentage",
            "performance_status",
            "performance_status_display",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "earned_value_percentage",
            "actual_billed_percentage",
            "variance",
            "variance_percentage",
            "performance_status",
            "performance_status_display",
            "created_at",
            "updated_at",
        ]
    
    def validate_contract_value(self, value):
        """Validate contract_value > 0"""
        if value is None:
            raise serializers.ValidationError("contract_value is required.")
        if value <= 0:
            raise serializers.ValidationError("contract_value must be greater than 0.")
        return value
    
    def validate_earned_value(self, value):
        """Validate earned_value >= 0"""
        if value is None:
            return Decimal("0")
        if value < 0:
            raise serializers.ValidationError("earned_value must be >= 0.")
        return value
    
    def validate_actual_billed(self, value):
        """Validate actual_billed >= 0"""
        if value is None:
            return Decimal("0")
        if value < 0:
            raise serializers.ValidationError("actual_billed must be >= 0.")
        return value
    
    def update(self, instance, validated_data):
        """
        Override update to handle updated_by field.
        """
        # If updated_by is not provided, try to get it from request context
        if "updated_by" not in validated_data:
            request = self.context.get("request")
            if request and hasattr(request, "data"):
                updated_by = request.data.get("updated_by")
                if updated_by:
                    validated_data["updated_by"] = updated_by
        
        return super().update(instance, validated_data)
