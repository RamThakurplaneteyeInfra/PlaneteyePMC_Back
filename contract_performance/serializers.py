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
        extra_kwargs = {
            'created_by': {'required': True},
        }

    def _validate_non_negative_decimal(self, value, field_name):
        """
        Reusable validation helper for non-negative decimal fields.
        Returns default Decimal("0") if None, otherwise validates >= 0.
        """
        if value is None:
            return Decimal("0")
        if value < 0:
            raise serializers.ValidationError(f"{field_name} must be >= 0.")
        return value

    def validate_project_name(self, value):
        """Validate and normalize project_name."""
        if not value or not value.strip():
            raise serializers.ValidationError("project_name cannot be blank.")
        return value.strip()

    def validate_contract_value(self, value):
        """Validate contract_value > 0."""
        if value is None:
            raise serializers.ValidationError("contract_value is required.")
        if value <= 0:
            raise serializers.ValidationError("contract_value must be greater than 0.")
        return value

    def validate_earned_value(self, value):
        """Validate earned_value >= 0 using helper method."""
        return self._validate_non_negative_decimal(value, "earned_value")

    def validate_actual_billed(self, value):
        """Validate actual_billed >= 0 using helper method."""
        return self._validate_non_negative_decimal(value, "actual_billed")

    def update(self, instance, validated_data):
        """
        Override update to handle updated_by field from serializer context.
        """
        # Extract updated_by from serializer context if not provided in validated_data
        if "updated_by" not in validated_data:
            # Try to get from serializer context first (preferred method)
            updated_by = self.context.get("updated_by")
            if not updated_by:
                # Fallback to request context for backward compatibility
                request = self.context.get("request")
                if request and hasattr(request, "data"):
                    updated_by = request.data.get("updated_by")
            if updated_by:
                validated_data["updated_by"] = updated_by

        return super().update(instance, validated_data)
