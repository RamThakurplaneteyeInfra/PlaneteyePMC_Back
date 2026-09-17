"""
Monthly Project Equipment Serializer.

Handles input validation and output formatting for ProjectEquipment records.

Calculated fields are always read-only — derived by the model's save():
  - variance
  - performancePercentage

Runtime-computed property exposed as read-only output:
  - equipmentStatus  (fully_deployed / near_target / shortfall / critical_shortfall)

Validation rules:
  - projectName      : required, non-blank string
  - equipmentMonth   : required, YYYY-MM format
  - plannedEquipment : integer >= 0
  - actualEquipment  : integer >= 0
  - remarks          : optional string

Accepts both camelCase (frontend default) and snake_case field names.
The controller normalises the payload before passing it to the serializer.
"""

import re

from rest_framework import serializers

from ..models.project_equipment import ProjectEquipment

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class ProjectEquipmentSerializer(serializers.ModelSerializer):
    """
    Full serializer for ProjectEquipment model.

    Read-only fields (auto-calculated by the model on every save):
      - id
      - variance
      - performancePercentage
      - created_at
      - updated_at

    Read-only computed property (derived at runtime, not stored):
      - equipmentStatus

    Writable fields:
      - projectName      (required)
      - equipmentMonth   (required, YYYY-MM)
      - plannedEquipment (>= 0)
      - actualEquipment  (>= 0)
      - remarks          (optional)
    """

    # Expose Python @property as a read-only serializer field
    equipmentStatus = serializers.CharField(read_only=True)

    # Override to remove auto-added UniqueTogetherValidator.
    # Our validate() method provides a friendlier duplicate error message.
    # DB unique_together still enforces true duplicates at the DB level.
    projectName = serializers.CharField(max_length=255)
    equipmentMonth = serializers.CharField(max_length=7)

    class Meta:
        model = ProjectEquipment
        fields = [
            "id",
            "projectName",
            "equipmentMonth",
            "plannedEquipment",
            "actualEquipment",
            "variance",
            "performancePercentage",
            "equipmentStatus",
            "remarks",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "variance",
            "performancePercentage",
            "equipmentStatus",
            "created_at",
            "updated_at",
        ]
        # Suppress auto-generated UniqueTogetherValidator so our custom
        # validate() method returns a friendlier error message.
        validators = []

    # -------------------------------------------------------------------------
    # Field-level validation
    # -------------------------------------------------------------------------

    def validate_projectName(self, value: str) -> str:
        if not value or not value.strip():
            raise serializers.ValidationError("projectName cannot be blank.")
        return value.strip()

    def validate_equipmentMonth(self, value: str) -> str:
        value = value.strip()
        if not _MONTH_RE.match(value):
            raise serializers.ValidationError(
                "equipmentMonth must be in YYYY-MM format (e.g. '2026-05')."
            )
        return value

    def validate_plannedEquipment(self, value: int) -> int:
        if value < 0:
            raise serializers.ValidationError("plannedEquipment must be >= 0.")
        return value

    def validate_actualEquipment(self, value: int) -> int:
        if value < 0:
            raise serializers.ValidationError("actualEquipment must be >= 0.")
        return value

    # -------------------------------------------------------------------------
    # Cross-field validation
    # -------------------------------------------------------------------------

    def validate(self, attrs: dict) -> dict:
        """
        Duplicate-month check on CREATE only.

        On update (self.instance is set) the controller already resolved the
        existing record by ID, so we skip the duplicate check here.
        """
        if self.instance is not None:
            return attrs

        project_name = attrs.get("projectName", "").strip()
        equipment_month = attrs.get("equipmentMonth", "").strip()

        if project_name and equipment_month:
            if ProjectEquipment.objects.filter(
                projectName__iexact=project_name,
                equipmentMonth=equipment_month,
            ).exists():
                raise serializers.ValidationError(
                    {
                        "equipmentMonth": (
                            f"An equipment record for project '{project_name}' "
                            f"in month '{equipment_month}' already exists. "
                            "Use PUT /api/project-equipment/{id}/ to update it."
                        )
                    }
                )

        return attrs
