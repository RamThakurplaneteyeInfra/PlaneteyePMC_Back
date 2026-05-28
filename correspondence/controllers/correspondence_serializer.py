"""
Correspondence Serializer.

Handles input validation and output formatting for Correspondence records.

Calculated fields (pendingCorrespondence, deliveryPercentage) are read-only —
they are always derived from correspondenceReceived / correspondenceDelivered
inside the model's save() method.

Validation rules enforced here (before the model even runs):
  - projectName       : required, non-blank string
  - correspondenceReceived   : integer >= 0
  - correspondenceDelivered  : integer >= 0, must not exceed correspondenceReceived
"""

from rest_framework import serializers

from ..models.correspondence import Correspondence


class CorrespondenceSerializer(serializers.ModelSerializer):
    """
    Full serializer for the Correspondence model.

    Read-only fields (auto-calculated by the model on every save):
      - id
      - pendingCorrespondence
      - deliveryPercentage
      - created_at
      - updated_at

    Writable fields:
      - projectName              (required, unique per project)
      - correspondenceReceived   (>= 0)
      - correspondenceDelivered  (>= 0, must not exceed correspondenceReceived)
    """

    class Meta:
        model = Correspondence
        fields = [
            "id",
            "projectName",
            "correspondenceReceived",
            "correspondenceDelivered",
            "pendingCorrespondence",
            "deliveryPercentage",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "pendingCorrespondence",
            "deliveryPercentage",
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

    def validate_correspondenceReceived(self, value: int) -> int:
        """Ensure correspondenceReceived is non-negative."""
        if value < 0:
            raise serializers.ValidationError(
                "correspondenceReceived must be >= 0."
            )
        return value

    def validate_correspondenceDelivered(self, value: int) -> int:
        """Ensure correspondenceDelivered is non-negative."""
        if value < 0:
            raise serializers.ValidationError(
                "correspondenceDelivered must be >= 0."
            )
        return value

    # -------------------------------------------------------------------------
    # Cross-field validation
    # -------------------------------------------------------------------------

    def validate(self, attrs: dict) -> dict:
        """
        Cross-field check: correspondenceDelivered must not exceed
        correspondenceReceived.

        For partial updates (PATCH / PUT with missing fields), fall back to
        the existing instance values so the check remains accurate even when
        only one of the two fields is being updated.
        """
        instance = self.instance  # None on create, existing object on update

        received = attrs.get(
            "correspondenceReceived",
            getattr(instance, "correspondenceReceived", 0) if instance else 0,
        )
        delivered = attrs.get(
            "correspondenceDelivered",
            getattr(instance, "correspondenceDelivered", 0) if instance else 0,
        )

        if delivered > received:
            raise serializers.ValidationError(
                {
                    "correspondenceDelivered": (
                        f"correspondenceDelivered ({delivered}) cannot be greater "
                        f"than correspondenceReceived ({received})."
                    )
                }
            )

        return attrs
