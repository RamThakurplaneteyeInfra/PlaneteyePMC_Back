from decimal import Decimal
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

    def validate_original_contract_value(self, value):
        """Validate original_contract_value > 0."""
        if value is None:
            raise serializers.ValidationError("original_contract_value is required.")
        if value <= 0:
            raise serializers.ValidationError("original_contract_value must be greater than 0.")
        return value

    def validate_approved_vo(self, value):
        """Validate approved_vo using helper method."""
        return self._validate_non_negative_decimal(value, "approved_vo")

    def validate_pending_vo(self, value):
        """Validate pending_vo using helper method."""
        return self._validate_non_negative_decimal(value, "pending_vo")

    def validate(self, attrs):
        """
        Perform cross-field validation and normalization.
        """
        # Ensure all monetary fields are Decimal for consistency
        monetary_fields = ['original_contract_value', 'approved_vo', 'pending_vo']
        for field in monetary_fields:
            if field in attrs and attrs[field] is not None:
                attrs[field] = Decimal(str(attrs[field]))

        return attrs

    def create(self, validated_data):
        """
        Create contract with proper defaults and workflow enforcement.
        """
        # Set default values for optional monetary fields
        validated_data.setdefault("approved_vo", Decimal("0"))
        validated_data.setdefault("pending_vo", Decimal("0"))

        # Workflow enforcement: status must be PENDING on create
        # Remove any provided status to prevent override
        validated_data.pop("status", None)
        validated_data["status"] = Contract.Status.PENDING

        return super().create(validated_data)

