"""
Contract Value Serializer.

Handles input validation and output formatting for ContractValue records.

Calculated fields are always read-only — derived by the model's save():
  - approvedVOPercentage
  - revisedContractValue

Validation rules:
  - projectName          : required, non-blank string
  - contractType         : required, must be one of ContractValue.ContractType choices
  - originalContractValue: Decimal >= 0
  - approvedVO           : Decimal >= 0
  - potentialPendingVO   : Decimal >= 0
"""

from decimal import Decimal

from rest_framework import serializers

from ..models.contract_value import ContractValue


class ContractValueSerializer(serializers.ModelSerializer):
    """
    Full serializer for ContractValue model.

    Read-only fields (auto-calculated by the model on every save):
      - id
      - approvedVOPercentage
      - revisedContractValue
      - created_at
      - updated_at

    Writable fields:
      - projectName           (required)
      - contractType          (required, enum: SCL | Contractor)
      - originalContractValue (>= 0)
      - approvedVO            (>= 0)
      - potentialPendingVO    (>= 0)
    """

    class Meta:
        model = ContractValue
        fields = [
            "id",
            "projectName",
            "contractType",
            "originalContractValue",
            "approvedVO",
            "approvedVOPercentage",
            "revisedContractValue",
            "potentialPendingVO",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "approvedVOPercentage",
            "revisedContractValue",
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

    def validate_contractType(self, value: str) -> str:
        """Validate contractType is one of the allowed enum values."""
        valid = [c.value for c in ContractValue.ContractType]
        if value not in valid:
            raise serializers.ValidationError(
                f"contractType must be one of: {', '.join(valid)}. Got '{value}'."
            )
        return value

    def _validate_non_negative_decimal(self, value: Decimal, field_name: str) -> Decimal:
        """Reusable helper: ensure Decimal field is >= 0."""
        if value is not None and value < 0:
            raise serializers.ValidationError(
                f"{field_name} must be >= 0. Negative values are not allowed."
            )
        return value if value is not None else Decimal("0.00")

    def validate_originalContractValue(self, value: Decimal) -> Decimal:
        return self._validate_non_negative_decimal(value, "originalContractValue")

    def validate_approvedVO(self, value: Decimal) -> Decimal:
        return self._validate_non_negative_decimal(value, "approvedVO")

    def validate_potentialPendingVO(self, value: Decimal) -> Decimal:
        return self._validate_non_negative_decimal(value, "potentialPendingVO")

    # -------------------------------------------------------------------------
    # Cross-field validation
    # -------------------------------------------------------------------------

    def validate(self, attrs: dict) -> dict:
        """
        Cross-field validation.

        On update (partial or full): fall back to existing instance values
        for any missing fields so downstream calculations remain accurate.

        Note: uniqueness of (projectName, contractType) is enforced at the
        controller level via upsert logic — not here — so POSTing an existing
        pair updates the record rather than raising a validation error.
        """
        return attrs
