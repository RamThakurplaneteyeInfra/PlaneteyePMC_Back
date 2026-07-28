"""
Project Dates Serializer.

Writable fields (sent by frontend):
  - project_name   : resolved to Project FK in validate()
  - date_type      : "SCL" or "CONTRACTOR"
  - contractor_name: required for CONTRACTOR, empty for SCL
  - project_start, contract_finish, forecast_finish
  - eot_date (optional)

Read-only calculated fields are computed at serialization time.
"""

from datetime import date

from rest_framework import serializers

from projects.models import Project

from contractors.resolvers import (
    contractor_payload,
    resolve_contractor_for_write,
    resolve_project_for_module,
)

from .bg_status import bg_status_for_project_date
from .models import ProjectDates


class ProjectDatesSerializer(serializers.ModelSerializer):
    """Full serializer for ProjectDates (SCL or named Contractor)."""

    project_name = serializers.SerializerMethodField()
    contractor = serializers.SerializerMethodField()
    contractor_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)

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
    delay_days = serializers.SerializerMethodField(
        help_text="Forecast delay: (forecast_finish - contract_finish).days",
    )
    eot_delay_days = serializers.SerializerMethodField(
        help_text="EOT extension: (eot_date - contract_finish).days",
    )
    current_delay = serializers.SerializerMethodField(
        help_text="Live overdue counter: (today - contract_finish).days",
    )
    bg_status = serializers.SerializerMethodField(
        help_text="BG entries scoped to this schedule row only.",
    )

    class Meta:
        model = ProjectDates
        fields = [
            "id",
            "project_name",
            "date_type",
            "contractor_name",
            "contractor",
            "contractor_id",
            "project_start",
            "contract_finish",
            "forecast_finish",
            "eot_date",
            "elapsed_duration",
            "remaining_duration",
            "forecast_finish_duration",
            "eot_duration",
            "delay_days",
            "eot_delay_days",
            "current_delay",
            "bg_status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "project_name",
            "contractor",
            "elapsed_duration",
            "remaining_duration",
            "forecast_finish_duration",
            "eot_duration",
            "delay_days",
            "eot_delay_days",
            "current_delay",
            "bg_status",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            "eot_date": {"required": False, "allow_null": True},
        }
        validators = []

    def to_internal_value(self, data):
        raw_project_name = data.get("project_name", "")
        ret = super().to_internal_value(data)
        ret["project_name"] = str(raw_project_name).strip()
        contractor_name = data.get("contractor_name")
        if contractor_name is not None:
            ret["contractor_name"] = str(contractor_name).strip()
        if "contractor_id" in data:
            ret["contractor_id"] = data.get("contractor_id")
        return ret

    def get_contractor(self, obj) -> dict | None:
        return contractor_payload(obj.contractor)

    def get_project_name(self, obj) -> str:
        return obj.project.name if obj.project_id else ""

    def get_elapsed_duration(self, obj) -> int:
        if obj.project_start:
            return (date.today() - obj.project_start).days
        return 0

    def get_remaining_duration(self, obj) -> int:
        if obj.contract_finish:
            return (obj.contract_finish - date.today()).days
        return 0

    def get_forecast_finish_duration(self, obj) -> int:
        if obj.forecast_finish and obj.contract_finish:
            return (obj.forecast_finish - obj.contract_finish).days
        return 0

    def get_eot_duration(self, obj) -> int:
        if obj.eot_date and obj.contract_finish:
            return (obj.eot_date - obj.contract_finish).days
        return 0

    def get_delay_days(self, obj) -> int:
        if obj.forecast_finish and obj.contract_finish:
            return (obj.forecast_finish - obj.contract_finish).days
        return 0

    def get_eot_delay_days(self, obj) -> int:
        if obj.eot_date and obj.contract_finish:
            return (obj.eot_date - obj.contract_finish).days
        return 0

    def get_current_delay(self, obj) -> int:
        if obj.contract_finish:
            return (date.today() - obj.contract_finish).days
        return 0

    def get_bg_status(self, obj) -> dict:
        return bg_status_for_project_date(obj)

    def validate(self, attrs: dict) -> dict:
        project_name = attrs.pop("project_name", "").strip()

        if not project_name:
            if self.instance is not None:
                attrs["project"] = self.instance.project
                project = self.instance.project
            else:
                raise serializers.ValidationError(
                    {"project_name": "project_name is required."}
                )
        else:
            project = resolve_project_for_module(project_name)
            attrs["project"] = project

        instance = self.instance
        date_type = attrs.get(
            "date_type",
            getattr(instance, "date_type", None) if instance else None,
        )
        contractor_name = attrs.get(
            "contractor_name",
            getattr(instance, "contractor_name", None) if instance else None,
        )
        contractor_id = attrs.pop("contractor_id", None)
        if contractor_id is None and hasattr(self, "initial_data"):
            contractor_id = self.initial_data.get("contractor_id")

        if date_type == ProjectDates.DATE_TYPE_SCL:
            attrs["contractor"] = None
            attrs["contractor_name"] = None
        elif date_type == ProjectDates.DATE_TYPE_CONTRACTOR:
            contractor = resolve_contractor_for_write(
                project,
                contractor_id=contractor_id,
                contractor_name=contractor_name,
            )
            attrs["contractor"] = contractor
            attrs["contractor_name"] = contractor.contractor_name

        project_start = attrs.get(
            "project_start",
            getattr(instance, "project_start", None) if instance else None,
        )
        contract_finish = attrs.get(
            "contract_finish",
            getattr(instance, "contract_finish", None) if instance else None,
        )
        eot_date = attrs.get(
            "eot_date",
            getattr(instance, "eot_date", None) if instance else None,
        )

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

        if instance is None:
            if date_type == ProjectDates.DATE_TYPE_SCL:
                if ProjectDates.objects.filter(
                    project=project,
                    date_type=ProjectDates.DATE_TYPE_SCL,
                ).exists():
                    raise serializers.ValidationError(
                        {
                            "date_type": (
                                f"A SCL record for project '{project.name}' already exists. "
                                "Use PATCH /api/project-dates/{id}/ to update it."
                            )
                        }
                    )
            elif date_type == ProjectDates.DATE_TYPE_CONTRACTOR:
                contractor = attrs.get("contractor")
                if contractor and ProjectDates.objects.filter(
                    project=project,
                    date_type=ProjectDates.DATE_TYPE_CONTRACTOR,
                    contractor_id=contractor.id,
                ).exists():
                    raise serializers.ValidationError(
                        {
                            "contractor_id": (
                                f"A contractor schedule for '{contractor.contractor_name}' "
                                f"already exists for project '{project.name}'."
                            )
                        }
                    )
        elif date_type == ProjectDates.DATE_TYPE_CONTRACTOR and attrs.get("contractor"):
            contractor = attrs["contractor"]
            if ProjectDates.objects.filter(
                project=project,
                date_type=ProjectDates.DATE_TYPE_CONTRACTOR,
                contractor_id=contractor.id,
            ).exclude(pk=instance.pk).exists():
                raise serializers.ValidationError(
                    {
                        "contractor_id": (
                            f"A contractor schedule for '{contractor.contractor_name}' "
                            f"already exists for project '{project.name}'."
                        )
                    }
                )

        return attrs

    def create(self, validated_data):
        validated_data.pop("project_name", None)
        return ProjectDates.objects.create(**validated_data)

    def update(self, instance, validated_data):
        validated_data.pop("project_name", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance
