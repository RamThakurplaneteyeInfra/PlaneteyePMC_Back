"""
Project Quality Status Serializer.

Handles input validation and output formatting for ProjectQualityStatus records.

Calculated fields are always read-only — derived by the model's save():
  - variance
  - performancePercentage

Runtime-computed properties exposed as read-only output:
  - qualityStatus  (excellent / good / average / poor)
  - failedTests    (alias for variance)

Validation rules:
  - projectName          : required, non-blank string
  - totalTestsConducted  : integer >= 0
  - totalTestsPassed     : integer >= 0, must not exceed totalTestsConducted
"""

from rest_framework import serializers

from ..models.project_quality_status import ProjectQualityStatus


class ProjectQualityStatusSerializer(serializers.ModelSerializer):
    """
    Full serializer for ProjectQualityStatus model.

    Read-only fields (auto-calculated by the model on every save):
      - id
      - variance
      - performancePercentage
      - created_at
      - updated_at

    Read-only computed properties (derived at runtime, not stored):
      - qualityStatus
      - failedTests

    Writable fields:
      - projectName         (required, unique per project)
      - totalTestsConducted (>= 0)
      - totalTestsPassed    (>= 0, must not exceed totalTestsConducted)
    """

    # Expose Python @property fields as read-only serializer fields
    qualityStatus = serializers.CharField(read_only=True)
    failedTests = serializers.IntegerField(read_only=True)

    # Override projectName to remove the auto-added UniqueValidator.
    # Uniqueness is enforced at the DB level; the controller handles upsert
    # logic manually so the validator would incorrectly reject updates.
    projectName = serializers.CharField(max_length=255)

    class Meta:
        model = ProjectQualityStatus
        fields = [
            "id",
            "projectName",
            "totalTestsConducted",
            "totalTestsPassed",
            # Auto-calculated stored fields
            "variance",
            "performancePercentage",
            # Computed runtime properties
            "qualityStatus",
            "failedTests",
            # Timestamps
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "variance",
            "performancePercentage",
            "qualityStatus",
            "failedTests",
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

    def validate_totalTestsConducted(self, value: int) -> int:
        """Ensure totalTestsConducted is non-negative."""
        if value < 0:
            raise serializers.ValidationError(
                "totalTestsConducted must be >= 0."
            )
        return value

    def validate_totalTestsPassed(self, value: int) -> int:
        """Ensure totalTestsPassed is non-negative."""
        if value < 0:
            raise serializers.ValidationError(
                "totalTestsPassed must be >= 0."
            )
        return value

    # -------------------------------------------------------------------------
    # Cross-field validation
    # -------------------------------------------------------------------------

    def validate(self, attrs: dict) -> dict:
        """
        Cross-field check: totalTestsPassed must not exceed totalTestsConducted.

        For partial updates (PATCH/PUT with missing fields), fall back to
        the existing instance values so the check remains accurate.
        """
        instance = self.instance  # None on create, existing object on update

        conducted = attrs.get(
            "totalTestsConducted",
            getattr(instance, "totalTestsConducted", 0) if instance else 0,
        )
        passed = attrs.get(
            "totalTestsPassed",
            getattr(instance, "totalTestsPassed", 0) if instance else 0,
        )

        if passed > conducted:
            raise serializers.ValidationError(
                {
                    "totalTestsPassed": (
                        f"totalTestsPassed ({passed}) cannot be greater than "
                        f"totalTestsConducted ({conducted})."
                    )
                }
            )

        return attrs
