"""
Monthly Construction Progress Serializer.

Handles input validation and output formatting for ConstructionProgress records.

Calculated fields are always read-only — derived by the model's save():
  - variance
  - performancePercentage

Runtime-computed property exposed as read-only output:
  - progressStatus  (on_track / slight_delay / delayed / critical)

Validation rules:
  - projectName     : required, non-blank string
  - progressMonth   : required, YYYY-MM format
  - plannedProgress : float 0–100
  - actualProgress  : float 0–100
  - remarks         : optional string

Accepts both camelCase (frontend default) and snake_case field names.
The controller normalises the payload before passing it to the serializer.
"""

import re

from rest_framework import serializers

from ..models.construction_progress import ConstructionProgress

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class ConstructionProgressSerializer(serializers.ModelSerializer):
    """
    Full serializer for ConstructionProgress model.

    Read-only fields (auto-calculated by the model on every save):
      - id
      - variance
      - performancePercentage
      - created_at
      - updated_at

    Read-only computed property (derived at runtime, not stored):
      - progressStatus

    Writable fields:
      - projectName     (required)
      - progressMonth   (required, YYYY-MM)
      - plannedProgress (0–100)
      - actualProgress  (0–100)
      - remarks         (optional)
    """

    # Expose Python @property as a read-only serializer field
    progressStatus = serializers.CharField(read_only=True)

    # Override to remove the auto-added UniqueTogetherValidator — the
    # controller handles upsert logic manually (find-then-update), and
    # we provide a friendlier duplicate error message in validate() below.
    # DB unique_together still enforces true duplicates at the DB level.
    projectName = serializers.CharField(max_length=255)
    progressMonth = serializers.CharField(max_length=7)

    class Meta:
        model = ConstructionProgress
        fields = [
            "id",
            "projectName",
            "progressMonth",
            "plannedProgress",
            "actualProgress",
            # Auto-calculated stored fields
            "variance",
            "performancePercentage",
            # Computed runtime property
            "progressStatus",
            # Optional
            "remarks",
            # Timestamps
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "variance",
            "performancePercentage",
            "progressStatus",
            "created_at",
            "updated_at",
        ]
        # Remove the auto-generated UniqueTogetherValidator so our custom
        # validate() method can return a friendlier error message.
        validators = []

    # -------------------------------------------------------------------------
    # Field-level validation
    # -------------------------------------------------------------------------

    def validate_projectName(self, value: str) -> str:
        """Strip whitespace and reject blank project names."""
        if not value or not value.strip():
            raise serializers.ValidationError("projectName cannot be blank.")
        return value.strip()

    def validate_progressMonth(self, value: str) -> str:
        """Enforce YYYY-MM format."""
        value = value.strip()
        if not _MONTH_RE.match(value):
            raise serializers.ValidationError(
                "progressMonth must be in YYYY-MM format (e.g. '2026-05')."
            )
        return value

    def validate_plannedProgress(self, value: float) -> float:
        """Ensure plannedProgress is between 0 and 100."""
        if value < 0:
            raise serializers.ValidationError("plannedProgress must be >= 0.")
        if value > 100:
            raise serializers.ValidationError("plannedProgress cannot exceed 100%.")
        return value

    def validate_actualProgress(self, value: float) -> float:
        """Ensure actualProgress is between 0 and 100."""
        if value < 0:
            raise serializers.ValidationError("actualProgress must be >= 0.")
        if value > 100:
            raise serializers.ValidationError("actualProgress cannot exceed 100%.")
        return value

    # -------------------------------------------------------------------------
    # Cross-field validation
    # -------------------------------------------------------------------------

    def validate(self, attrs: dict) -> dict:
        """
        Duplicate-month check on CREATE only.

        On update (self.instance is set) the controller already resolved the
        existing record, so we skip the duplicate check here.
        """
        if self.instance is not None:
            # Update path — no duplicate check needed
            return attrs

        project_name = attrs.get("projectName", "").strip()
        progress_month = attrs.get("progressMonth", "").strip()

        if project_name and progress_month:
            if ConstructionProgress.objects.filter(
                projectName__iexact=project_name,
                progressMonth=progress_month,
            ).exists():
                raise serializers.ValidationError(
                    {
                        "progressMonth": (
                            f"A progress record for project '{project_name}' "
                            f"in month '{progress_month}' already exists. "
                            "Use PUT /api/construction-progress/{id}/ to update it."
                        )
                    }
                )

        return attrs
