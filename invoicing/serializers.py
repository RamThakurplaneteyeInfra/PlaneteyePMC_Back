from decimal import Decimal
from rest_framework import serializers
from .models import InvoicingInformation


class InvoicingInformationSerializer(serializers.ModelSerializer):
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
        if value is None:
            return Decimal("0")
        if value < 0:
            raise serializers.ValidationError("gross_billed must be >= 0.")
        return value
    
    def validate_net_billed_without_vat(self, value):
        """Validate net_billed_without_vat >= 0"""
        if value is None:
            return Decimal("0")
        if value < 0:
            raise serializers.ValidationError("net_billed_without_vat must be >= 0.")
        return value
    
    def validate_net_collected(self, value):
        """Validate net_collected >= 0"""
        if value is None:
            return Decimal("0")
        if value < 0:
            raise serializers.ValidationError("net_collected must be >= 0.")
        return value
    
    def validate(self, attrs):
        """
        Additional validation:
        - Ensure net_collected <= net_billed_without_vat (logical constraint)
        """
        net_billed = attrs.get("net_billed_without_vat")
        if net_billed is None and self.instance:
            net_billed = self.instance.net_billed_without_vat
        if net_billed is None:
            net_billed = Decimal("0")
        
        net_collected = attrs.get("net_collected")
        if net_collected is None and self.instance:
            net_collected = self.instance.net_collected
        if net_collected is None:
            net_collected = Decimal("0")
        
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
            request = self.context.get("request")
            if request and hasattr(request, "data"):
                updated_by = request.data.get("updated_by")
                if updated_by:
                    validated_data["updated_by"] = updated_by
        
        return super().update(instance, validated_data)
