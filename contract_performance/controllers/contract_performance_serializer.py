"""
Contract Performance Serializer.

Handles input validation and output formatting for ContractPerformance records.

Accepts BOTH camelCase and snake_case field names from the frontend:
  - projectName  OR  project_name
  - billedValue  OR  billed_value
  - actualReceiptValue  OR  actual_receipt_value

Calculated fields are always read-only — derived by the model's save():
  - variance
  - variancePercentage
  - performancePercentage

Runtime-computed properties exposed as read-only output:
  - collectionEfficiency  (actualReceiptValue / billedValue)
  - performanceStatus     (excellent / good / average / poor)

Validation rules:
  - projectName         : required, non-blank string
  - billedValue         : Decimal >= 0
  - actualReceiptValue  : Decimal >= 0
"""

import logging
from decimal import Decimal

from rest_framework import serializers

from ..models.contract_performance import ContractPerformance

logger = logging.getLogger(__name__)
_ZERO = Decimal("0.00")


class ContractPerformanceSerializer(serializers.ModelSerializer):
    """
    Full serializer for ContractPerformance model.

    Read-only fields (auto-calculated by the model on every save):
      - id
      - variance
      - variancePercentage
      - performancePercentage
      - created_at
      - updated_at

    Read-only computed properties (derived at runtime, not stored):
      - collectionEfficiency
      - performanceStatus

    Writable fields:
      - projectName        (required, unique per project)
      - billedValue        (>= 0)
      - actualReceiptValue (>= 0)
    """

    # Expose Python @property fields as read-only serializer fields
    collectionEfficiency = serializers.FloatField(read_only=True)
    performanceStatus = serializers.CharField(read_only=True)

    class Meta:
        model = ContractPerformance
        fields = [
            "id",
            "projectName",
            "billedValue",
            "actualReceiptValue",
            # Auto-calculated stored fields
            "variance",
            "variancePercentage",
            "performancePercentage",
            # Computed runtime properties
            "collectionEfficiency",
            "performanceStatus",
            # Timestamps
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "variance",
            "variancePercentage",
            "performancePercentage",
            "collectionEfficiency",
            "performanceStatus",
            "created_at",
            "updated_at",
        ]

    # -------------------------------------------------------------------------
    # Snake_case → camelCase field normalisation
    # -------------------------------------------------------------------------

    def to_internal_value(self, data):
        """
        Normalise incoming data before validation.

        Accepts both camelCase (canonical) and snake_case variants so the
        frontend can send either format without causing a 400 error.

        Mapping:
          project_name          → projectName
          billed_value          → billedValue
          actual_receipt_value  → actualReceiptValue
        """
        # Work on a mutable copy
        data = dict(data)

        _aliases = {
            "project_name": "projectName",
            "billed_value": "billedValue",
            "actual_receipt_value": "actualReceiptValue",
        }

        for snake, camel in _aliases.items():
            if snake in data and camel not in data:
                data[camel] = data.pop(snake)
                logger.debug(
                    "ContractPerformanceSerializer: normalised '%s' → '%s'",
                    snake, camel,
                )

        return super().to_internal_value(data)

    # -------------------------------------------------------------------------
    # Field-level validation
    # -------------------------------------------------------------------------

    def validate_projectName(self, value: str) -> str:
        """Strip whitespace and reject blank project names."""
        if not value or not value.strip():
            raise serializers.ValidationError("projectName cannot be blank.")
        return value.strip()

    def _validate_non_negative_decimal(
        self, value: Decimal, field_name: str
    ) -> Decimal:
        """Reusable helper: ensure Decimal field is >= 0."""
        if value is not None and value < 0:
            raise serializers.ValidationError(
                f"{field_name} must be >= 0. Negative values are not allowed."
            )
        return value if value is not None else _ZERO

    def validate_billedValue(self, value: Decimal) -> Decimal:
        return self._validate_non_negative_decimal(value, "billedValue")

    def validate_actualReceiptValue(self, value: Decimal) -> Decimal:
        return self._validate_non_negative_decimal(value, "actualReceiptValue")

    # -------------------------------------------------------------------------
    # Cross-field validation
    # -------------------------------------------------------------------------

    def validate(self, attrs: dict) -> dict:
        """
        Cross-field validation.

        Both billedValue and actualReceiptValue must be non-negative.
        actualReceiptValue > billedValue is intentionally allowed
        (over-collection edge case).

        For partial updates, fall back to existing instance values
        so validation is accurate even when only one field is sent.
        """
        instance = self.instance  # None on create, existing object on update

        billed = attrs.get(
            "billedValue",
            getattr(instance, "billedValue", _ZERO) if instance else _ZERO,
        )
        receipt = attrs.get(
            "actualReceiptValue",
            getattr(instance, "actualReceiptValue", _ZERO) if instance else _ZERO,
        )

        if billed < 0:
            raise serializers.ValidationError(
                {"billedValue": "billedValue must be >= 0."}
            )
        if receipt < 0:
            raise serializers.ValidationError(
                {"actualReceiptValue": "actualReceiptValue must be >= 0."}
            )

        return attrs
