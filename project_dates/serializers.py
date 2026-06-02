"""
Project Dates Serializer.

Writable fields (sent by frontend):
  - project_name   : resolved to Project FK in validate()
  - date_type      : "SCL" or "CONTRACTOR"
  - project_start
  - contract_finish
  - forecast_finish
  - eot_date

Read-only calculated fields (computed at serialization time, NOT stored in DB):
  - elapsed_duration         = (today - project_start).days
  - remaining_duration       = (contract_finish - today).days
  - forecast_finish_duration = (forecast_finish - contract_finish).days
  - eot_duration             = (eot_date - contract_finish).days

project_name is handled via:
  - INPUT  : to_internal_value() extracts it before DRF field processing
  - OUTPUT : SerializerMethodField reads it from instance.project.name
"""

from datetime import date

from rest_framework import serializers

from projects.models import Project
from .models import ProjectDates


class ProjectDatesSerializer(serializers.ModelSerializer):
    """
    Full serializer for ProjectDates.

    project_name is a virtual field:
      - On write: extracted in to_internal_value(), resolved to a Project FK in validate()
      - On read:  returned via get_project_name() from the FK

    All four duration fields are SerializerMethodFields — computed fresh on
    every read so they always reflect today's date accurately.
    """

    # -------------------------------------------------------------------------
    # project_name — read path (output only, source = FK traversal)
    # -------------------------------------------------------------------------
    project_name = serializers.SerializerMethodField()

    # -------------------------------------------------------------------------
    # Calculated duration fields (read-only, not stored in DB)
    # -------------------------------------------------------------------------
    elapsed_duration = serializers.SerializerMethodField(
        help_text="Days from project_start to today",
    )
    remaining_duration = serializers.SerializerMethodField(
        help_text="Days from today to contract_finish",
    )
    forecast_finish_duration = serializers.SerializerMethodField(
        help_text="Days between forecast_finish and contract_finish",
    )
    eot_duration = serializers.SerializerMethodField(
        help_text="Days between eot_date and contract_finish",
    )

    # -------------------------------------------------------------------------
    # Delay fields (read-only, not stored in DB)
    # -------------------------------------------------------------------------
    delay_days = serializers.SerializerMethodField(
        help_text=(
            "Forecast delay: (forecast_finish - contract_finish).days. "
            "Positive = project is delayed beyond contract finish. "
            "0 = on schedule."
        ),
    )
    eot_delay_days = serializers.SerializerMethodField(
        help_text=(
            "EOT extension: (eot_date - contract_finish).days. "
            "How many extra days the EOT grants beyond the original contract finish."
        ),
    )
    current_delay = serializers.SerializerMethodField(
        help_text=(
            "Live overdue counter: (today - contract_finish).days. "
            "Positive = already past contract finish date. "
            "Negative = still within contract period. "
            "0 = contract finish is today."
        ),
    )

    class Meta:
        model = ProjectDates
        fields = [
            "id",
            "project_name",
            "date_type",
            "project_start",
            "contract_finish",
            "forecast_finish",
            "eot_date",
            # Duration calculations
            "elapsed_duration",
            "remaining_duration",
            "forecast_finish_duration",
            "eot_duration",
            # Delay calculations
            "delay_days",
            "eot_delay_days",
            "current_delay",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "project_name",
            "elapsed_duration",
            "remaining_duration",
            "forecast_finish_duration",
            "eot_duration",
            "delay_days",
            "eot_delay_days",
            "current_delay",
            "created_at",
            "updated_at",
        ]
        # Suppress auto-generated UniqueTogetherValidator — validate() provides
        # a friendlier duplicate error message.
        validators = []

    # -------------------------------------------------------------------------
    # to_internal_value: intercept project_name from raw input before
    # DRF field processing so it is available in validate()
    # -------------------------------------------------------------------------

    def to_internal_value(self, data):
        # Stash project_name from raw input — it is not a model field so DRF
        # would otherwise discard it.
        raw_project_name = data.get("project_name", "")
        ret = super().to_internal_value(data)
        ret["project_name"] = str(raw_project_name).strip()
        return ret

    # -------------------------------------------------------------------------
    # Output: project_name from FK
    # -------------------------------------------------------------------------

    def get_project_name(self, obj) -> str:
        return obj.project.name if obj.project_id else ""

    # -------------------------------------------------------------------------
    # Calculated field methods
    # -------------------------------------------------------------------------

    def get_elapsed_duration(self, obj) -> int:
        """Days from project_start to today."""
        if obj.project_start:
            return (date.today() - obj.project_start).days
        return 0

    def get_remaining_duration(self, obj) -> int:
        """Days from today to contract_finish (negative = past deadline)."""
        if obj.contract_finish:
            return (obj.contract_finish - date.today()).days
        return 0

    def get_forecast_finish_duration(self, obj) -> int:
        """Days between forecast_finish and contract_finish."""
        if obj.forecast_finish and obj.contract_finish:
            return (obj.forecast_finish - obj.contract_finish).days
        return 0

    def get_eot_duration(self, obj) -> int:
        """Days between eot_date and contract_finish."""
        if obj.eot_date and obj.contract_finish:
            return (obj.eot_date - obj.contract_finish).days
        return 0

    def get_delay_days(self, obj) -> int:
        """
        Forecast delay = forecast_finish - contract_finish.
        Positive  → project is delayed beyond the original contract finish.
        Zero      → forecast matches contract finish exactly (on schedule).
        """
        if obj.forecast_finish and obj.contract_finish:
            return (obj.forecast_finish - obj.contract_finish).days
        return 0

    def get_eot_delay_days(self, obj) -> int:
        """
        EOT extension = eot_date - contract_finish.
        How many additional days the Extension of Time grants beyond
        the original contract finish date.
        """
        if obj.eot_date and obj.contract_finish:
            return (obj.eot_date - obj.contract_finish).days
        return 0

    def get_current_delay(self, obj) -> int:
        """
        Live overdue counter = today - contract_finish.
        Positive  → already past the contract finish date (overdue).
        Negative  → still within the contract period (days left).
        Zero      → contract finish is today.
        """
        if obj.contract_finish:
            return (date.today() - obj.contract_finish).days
        return 0

    # -------------------------------------------------------------------------
    # Cross-field validation
    # -------------------------------------------------------------------------

    def validate(self, attrs: dict) -> dict:
        """
        1. Resolve project_name → Project FK.
        2. Enforce date ordering rules.
        3. Reject duplicate (project + date_type) on CREATE.
        """
        # --- 1. Resolve project ---
        project_name = attrs.pop("project_name", "").strip()

        # On partial update, project_name is optional — fall back to instance
        if not project_name:
            if self.instance is not None:
                attrs["project"] = self.instance.project
            else:
                raise serializers.ValidationError(
                    {"project_name": "project_name is required."}
                )
        else:
            try:
                project = Project.objects.get(name__iexact=project_name)
            except Project.DoesNotExist:
                raise serializers.ValidationError(
                    {"project_name": f"No project found with name '{project_name}'."}
                )
            attrs["project"] = project

        # --- 2. Date ordering (fall back to instance values on partial update) ---
        instance = self.instance
        project_start   = attrs.get("project_start",   getattr(instance, "project_start",   None) if instance else None)
        contract_finish = attrs.get("contract_finish", getattr(instance, "contract_finish", None) if instance else None)
        forecast_finish = attrs.get("forecast_finish", getattr(instance, "forecast_finish", None) if instance else None)
        eot_date        = attrs.get("eot_date",        getattr(instance, "eot_date",        None) if instance else None)

        errors = {}
        if project_start and contract_finish and project_start > contract_finish:
            errors["project_start"] = (
                f"project_start ({project_start}) must be on or before "
                f"contract_finish ({contract_finish})."
            )
        if contract_finish and eot_date and contract_finish > eot_date:
            errors["eot_date"] = (
                f"eot_date ({eot_date}) must be on or after "
                f"contract_finish ({contract_finish})."
            )
        if errors:
            raise serializers.ValidationError(errors)

        # --- 3. Duplicate check on CREATE only ---
        if instance is None:
            date_type = attrs.get("date_type", "")
            if ProjectDates.objects.filter(project=project, date_type=date_type).exists():
                raise serializers.ValidationError(
                    {
                        "date_type": (
                            f"A {date_type} record for project '{project_name}' "
                            "already exists. "
                            "Use PUT /api/project-dates/{id}/ to update it."
                        )
                    }
                )

        return attrs

    # -------------------------------------------------------------------------
    # Create / Update
    # -------------------------------------------------------------------------

    def create(self, validated_data):
        validated_data.pop("project_name", None)
        return ProjectDates.objects.create(**validated_data)

    def update(self, instance, validated_data):
        validated_data.pop("project_name", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance
