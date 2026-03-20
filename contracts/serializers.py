from decimal import Decimal, InvalidOperation
from rest_framework import serializers
from .models import Contract


class ContractSerializer(serializers.ModelSerializer):
    """
    Serializer for Contract workflow.

    Notes:
    - Calculated fields are read-only and set only on CEO approval.
    - status is also controlled by workflow actions (create/approve/reject).
    """

    class Meta:
        model = Contract
        fields = [
            "id",
            "project_name",
            "original_contract_value",
            "approved_vo",
            "pending_vo",
            "revised_contract_value",
            "approved_vo_percentage",
            "status",
            "created_by",
            "approved_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "revised_contract_value",
            "approved_vo_percentage",
            "status",
            "approved_by",
            "created_at",
            "updated_at",
        ]

    def validate_original_contract_value(self, value):
        if value is None:
            raise serializers.ValidationError("original_contract_value is required.")
        if value <= 0:
            raise serializers.ValidationError("original_contract_value must be greater than 0.")
        return value

    def validate_approved_vo(self, value):
        if value is None:
            return Decimal("0")
        if value < 0:
            raise serializers.ValidationError("approved_vo must be >= 0.")
        return value

    def validate_pending_vo(self, value):
        if value is None:
            return Decimal("0")
        if value < 0:
            raise serializers.ValidationError("pending_vo must be >= 0.")
        return value

    def create(self, validated_data):
        # On create -> status must be pending (explicitly set, prevent any override)
        # Remove status from validated_data if present to force our value
        validated_data.pop("status", None)
        validated_data["status"] = Contract.Status.PENDING
        return super().create(validated_data)

