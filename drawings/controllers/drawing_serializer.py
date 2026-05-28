"""
Drawing Serializer.

Handles input validation and output formatting for Drawing records.
Calculated fields (variance, approvalPercentage) are read-only —
they are always derived from totalSubmitted / totalApproved in the model.
"""

from rest_framework import serializers

from ..models.drawing import Drawing


class DrawingSerializer(serializers.ModelSerializer):
    """
    Full serializer for Drawing model.

    Read-only fields (auto-calculated by the model):
      - id
      - variance
      - approvalPercentage
      - created_at
      - updated_at

    Writable fields:
      - projectName  (required, unique)
      - totalSubmitted (≥ 0)
      - totalApproved  (≥ 0, must not exceed totalSubmitted)
    """

    class Meta:
        model = Drawing
        fields = [
            "id",
            "projectName",
            "totalSubmitted",
            "totalApproved",
            "variance",
            "approvalPercentage",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "variance",
            "approvalPercentage",
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

    def validate_totalSubmitted(self, value: int) -> int:
        """Ensure totalSubmitted is non-negative."""
        if value < 0:
            raise serializers.ValidationError("totalSubmitted must be >= 0.")
        return value

    def validate_totalApproved(self, value: int) -> int:
        """Ensure totalApproved is non-negative."""
        if value < 0:
            raise serializers.ValidationError("totalApproved must be >= 0.")
        return value

    # -------------------------------------------------------------------------
    # Cross-field validation
    # -------------------------------------------------------------------------

    def validate(self, attrs: dict) -> dict:
        """
        Cross-field check: totalApproved must not exceed totalSubmitted.

        For partial updates (PATCH/PUT with missing fields), fall back to
        the existing instance values so the check remains accurate.
        """
        instance = self.instance  # None on create, existing object on update

        total_submitted = attrs.get(
            "totalSubmitted",
            getattr(instance, "totalSubmitted", 0) if instance else 0,
        )
        total_approved = attrs.get(
            "totalApproved",
            getattr(instance, "totalApproved", 0) if instance else 0,
        )

        if total_approved > total_submitted:
            raise serializers.ValidationError(
                {
                    "totalApproved": (
                        f"totalApproved ({total_approved}) cannot be greater than "
                        f"totalSubmitted ({total_submitted})."
                    )
                }
            )

        return attrs
