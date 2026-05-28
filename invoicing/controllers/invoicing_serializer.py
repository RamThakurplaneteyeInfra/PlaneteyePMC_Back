"""
Invoicing Information Serializer.

Handles input validation and output formatting for InvoicingInformation records.

Calculated field is always read-only — derived by the model's save():
  - netDue = netBilledWithoutVAT - netCollected

Validation rules:
  - projectName        : required, non-blank string
  - invoiceType        : required, must be one of InvoicingInformation.InvoiceType choices
  - grossBilled        : Decimal >= 0
  - netBilledWithoutVAT: Decimal >= 0
  - netCollected       : Decimal >= 0, must not exceed netBilledWithoutVAT
"""

from decimal import Decimal

from rest_framework import serializers

from ..models.invoicing_information import InvoicingInformation

# Reusable zero constant
_ZERO = Decimal("0.00")


class InvoicingInformationSerializer(serializers.ModelSerializer):
    """
    Full serializer for InvoicingInformation model.

    Read-only fields (auto-calculated by the model on every save):
      - id
      - netDue
      - created_at
      - updated_at

    Writable fields:
      - projectName         (required)
      - invoiceType         (required, enum: PMC | Contractor)
      - grossBilled         (>= 0)
      - netBilledWithoutVAT (>= 0)
      - netCollected        (>= 0, must not exceed netBilledWithoutVAT)
    """

    class Meta:
        model = InvoicingInformation
        fields = [
            "id",
            "projectName",
            "invoiceType",
            "grossBilled",
            "netBilledWithoutVAT",
            "netCollected",
            "netDue",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "netDue",
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

    def validate_invoiceType(self, value: str) -> str:
        """Validate invoiceType is one of the allowed enum values."""
        valid = [c.value for c in InvoicingInformation.InvoiceType]
        if value not in valid:
            raise serializers.ValidationError(
                f"invoiceType must be one of: {', '.join(valid)}. Got '{value}'."
            )
        return value

    def _validate_non_negative_decimal(
        self, value: Decimal, field_name: str
    ) -> Decimal:
        """Reusable helper: ensure Decimal field is >= 0."""
        if value is not None and value < 0:
            raise serializers.ValidationError(
                f"{field_name} must be >= 0. Negative values are not allowed."
            )
        return value if value is not None else _ZERO

    def validate_grossBilled(self, value: Decimal) -> Decimal:
        return self._validate_non_negative_decimal(value, "grossBilled")

    def validate_netBilledWithoutVAT(self, value: Decimal) -> Decimal:
        return self._validate_non_negative_decimal(value, "netBilledWithoutVAT")

    def validate_netCollected(self, value: Decimal) -> Decimal:
        return self._validate_non_negative_decimal(value, "netCollected")

    # -------------------------------------------------------------------------
    # Cross-field validation
    # -------------------------------------------------------------------------

    def validate(self, attrs: dict) -> dict:
        """
        Cross-field validation:
          netCollected must not exceed netBilledWithoutVAT.

        For partial updates, fall back to existing instance values
        so validation is accurate even when only one field is sent.

        Note: uniqueness of (projectName, invoiceType) is enforced at the
        controller level via upsert logic — not here — so POSTing an existing
        pair updates the record rather than raising a validation error.
        """
        instance = self.instance  # None on create, existing object on update

        # ── Resolve effective values (partial-update safe) ──────────────────
        net_billed = attrs.get(
            "netBilledWithoutVAT",
            getattr(instance, "netBilledWithoutVAT", _ZERO) if instance else _ZERO,
        )
        net_collected = attrs.get(
            "netCollected",
            getattr(instance, "netCollected", _ZERO) if instance else _ZERO,
        )

        # ── netCollected <= netBilledWithoutVAT ──────────────────────────────
        if net_collected > net_billed:
            raise serializers.ValidationError(
                {
                    "netCollected": (
                        f"netCollected ({net_collected}) cannot exceed "
                        f"netBilledWithoutVAT ({net_billed})."
                    )
                }
            )

        return attrs
