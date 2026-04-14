from decimal import Decimal
from rest_framework import serializers
from .models import InvoicingInformation

# Constants
ZERO = Decimal("0")


class InvoicingInformationSerializer(serializers.ModelSerializer):
    """
    Serializer for Invoicing Information.

    Notes:
    - net_due is auto-calculated (read-only)
    - All monetary fields use DecimalField for precision
    - Validation ensures non-negative values
    """

    def _validate_non_negative_decimal(self, value, field_name):
        """
        Helper method to validate non-negative Decimal values.
        Returns ZERO if None, raises ValidationError if negative.
        """
        if value is None:
            return ZERO
        if value < ZERO:
            raise serializers.ValidationError(f"{field_name} must be >= 0.")
        return value
    """
    Serializer for Invoicing Information.
    
    Notes:
    - net_due is auto-calculated (read-only)
    - All monetary fields use DecimalField for precision
    - Validation ensures non-negative values
    """
    
    class Meta:
        model = InvoicingInformation
        fields = [
            "id",
            "project_name",
            "gross_billed",
            "net_billed_without_vat",
            "net_collected",
            "net_due",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "net_due",  # Auto-calculated
            "created_at",
            "updated_at",
        ]
    
    def validate_gross_billed(self, value):
        """Validate gross_billed >= 0"""
        return self._validate_non_negative_decimal(value, "gross_billed")

    def validate_net_billed_without_vat(self, value):
        """Validate net_billed_without_vat >= 0"""
        return self._validate_non_negative_decimal(value, "net_billed_without_vat")

    def validate_net_collected(self, value):
        """Validate net_collected >= 0"""
        return self._validate_non_negative_decimal(value, "net_collected")
    
    def validate(self, attrs):
        """
        Additional validation:
        - Ensure net_collected <= net_billed_without_vat (logical constraint)
        - Normalize project_name
        """
        # Normalize project_name
        if "project_name" in attrs and attrs["project_name"]:
            attrs["project_name"] = attrs["project_name"].strip()

        # Get values with fallback: validated_data -> instance -> ZERO
        net_billed = (
            attrs.get("net_billed_without_vat") or
            (self.instance.net_billed_without_vat if self.instance else None) or
            ZERO
        )
        net_collected = (
            attrs.get("net_collected") or
            (self.instance.net_collected if self.instance else None) or
            ZERO
        )

        if net_collected > net_billed:
            raise serializers.ValidationError({
                "net_collected": "net_collected cannot exceed net_billed_without_vat."
            })

        return attrs
    
    def update(self, instance, validated_data):
        """
        Override update to handle updated_by field.
        """
        # If updated_by is not provided, try to get it from request context
        if "updated_by" not in validated_data:
            updated_by = self.context.get("request", {}).data.get("updated_by")
            if updated_by:
                validated_data["updated_by"] = updated_by

        return super().update(instance, validated_data)
