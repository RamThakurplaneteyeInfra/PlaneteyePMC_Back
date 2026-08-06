"""
ProjectEOT serializers — legacy Project Dates field names + additive EOT fields.

Request/response use familiar Project Dates names:
  project_name, date_type, contractor_*, project_start, contract_finish,
  forecast_finish, eot_date, duration fields…

Additive only:
  eot_number, extension_days, reason, remarks, status, approval_date,
  supporting_document(_url), is_active, current_eot, eot_count, eot_history
"""

from __future__ import annotations

from datetime import date

from django.utils.dateparse import parse_date
from rest_framework import serializers

from contractors.resolvers import (
    contractor_payload,
    resolve_contractor_for_write,
    resolve_project_for_module,
)
from project_dates.eot_models import ProjectEOT
from project_dates.eot_services import (
    compute_revised_date,
    next_eot_number,
    original_completion_for_project,
)
from project_dates.models import ProjectDates


class ProjectEOTSerializer(serializers.Serializer):
    """
    Hybrid serializer: writes ProjectEOT, speaks Project Dates field names.
    """

    @staticmethod
    def _as_date(value):
        if value is None or value == "":
            return None
        if isinstance(value, date):
            return value
        parsed = parse_date(str(value)[:10])
        return parsed

    # ---- Identity / schedule (legacy names) ----
    id = serializers.IntegerField(read_only=True)
    project_name = serializers.CharField(required=False, allow_blank=True)
    date_type = serializers.ChoiceField(
        choices=[ProjectDates.DATE_TYPE_SCL, ProjectDates.DATE_TYPE_CONTRACTOR],
        required=False,
        allow_null=True,
        default=ProjectDates.DATE_TYPE_SCL,
    )
    contractor_id = serializers.IntegerField(
        required=False, allow_null=True, write_only=False
    )
    contractor_name = serializers.CharField(
        required=False, allow_blank=True, allow_null=True
    )
    contractor = serializers.SerializerMethodField(read_only=True)

    project_start = serializers.DateField(required=False, allow_null=True)
    contract_finish = serializers.DateField(required=False, allow_null=True)
    forecast_finish = serializers.DateField(required=False, allow_null=True)
    eot_date = serializers.DateField(required=False, allow_null=True)

    # ---- Legacy computed durations (read-only) ----
    elapsed_duration = serializers.SerializerMethodField()
    remaining_duration = serializers.SerializerMethodField()
    forecast_finish_duration = serializers.SerializerMethodField()
    eot_duration = serializers.SerializerMethodField()
    delay_days = serializers.SerializerMethodField()
    eot_delay_days = serializers.SerializerMethodField()
    current_delay = serializers.SerializerMethodField()

    # ---- Additive EOT fields ----
    eot_number = serializers.IntegerField(required=False)
    extension_days = serializers.IntegerField(required=False)
    reason = serializers.CharField(required=False, allow_blank=True, default="")
    remarks = serializers.CharField(required=False, allow_blank=True, default="")
    status = serializers.ChoiceField(
        choices=[c[0] for c in ProjectEOT.STATUS_CHOICES],
        required=False,
        default=ProjectEOT.STATUS_PENDING,
    )
    approval_date = serializers.DateField(required=False, allow_null=True)
    supporting_document = serializers.FileField(
        required=False, allow_null=True, write_only=False
    )
    supporting_document_url = serializers.SerializerMethodField()
    is_active = serializers.BooleanField(required=False, default=True)

    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)
    created_by = serializers.IntegerField(source="created_by_id", read_only=True)
    updated_by = serializers.IntegerField(source="updated_by_id", read_only=True)
    created_by_name = serializers.SerializerMethodField()
    updated_by_name = serializers.SerializerMethodField()

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _schedule_row(self, obj: ProjectEOT) -> ProjectDates | None:
        if getattr(obj, "_schedule_row_resolved", False):
            return getattr(obj, "_cached_schedule_row", None)

        row: ProjectDates | None = None
        if obj.project_dates_id:
            row = obj.project_dates
        else:
            project = None
            # Prefer already-loaded project with SCL prefetch (project list).
            try:
                project = obj.project
            except Exception:
                project = None
            scl = getattr(project, "_prefetched_scl_dates", None) if project else None
            if scl is not None:
                row = scl[0] if scl else None
            elif obj.project_id:
                row = (
                    ProjectDates.objects.filter(
                        project_id=obj.project_id,
                        date_type=ProjectDates.DATE_TYPE_SCL,
                    )
                    .select_related("contractor")
                    .order_by("id")
                    .first()
                )

        obj._cached_schedule_row = row
        obj._schedule_row_resolved = True
        return row

    def _user_name(self, user) -> str | None:
        if not user:
            return None
        name = f"{user.first_name} {user.last_name}".strip()
        return name or user.username

    def get_contractor(self, obj) -> dict | None:
        pd = self._schedule_row(obj)
        if pd and pd.contractor_id:
            return contractor_payload(pd.contractor)
        return None

    def get_supporting_document_url(self, obj) -> str | None:
        if not obj.supporting_document:
            return None
        request = self.context.get("request")
        url = obj.supporting_document.url
        if request:
            return request.build_absolute_uri(url)
        return url

    def get_created_by_name(self, obj) -> str | None:
        return self._user_name(obj.created_by)

    def get_updated_by_name(self, obj) -> str | None:
        return self._user_name(obj.updated_by)

    def get_elapsed_duration(self, obj) -> int:
        pd = self._schedule_row(obj)
        start = pd.project_start if pd else None
        if start:
            return (date.today() - start).days
        return 0

    def get_remaining_duration(self, obj) -> int:
        finish = obj.original_completion_date
        if finish:
            return (finish - date.today()).days
        return 0

    def get_forecast_finish_duration(self, obj) -> int:
        pd = self._schedule_row(obj)
        if pd and pd.forecast_finish and pd.contract_finish:
            return (pd.forecast_finish - pd.contract_finish).days
        return 0

    def get_eot_duration(self, obj) -> int:
        if obj.revised_completion_date and obj.original_completion_date:
            return (obj.revised_completion_date - obj.original_completion_date).days
        return obj.extension_days or 0

    def get_delay_days(self, obj) -> int:
        return self.get_forecast_finish_duration(obj)

    def get_eot_delay_days(self, obj) -> int:
        return self.get_eot_duration(obj)

    def get_current_delay(self, obj) -> int:
        finish = obj.original_completion_date
        if finish:
            return (date.today() - finish).days
        return 0

    # -------------------------------------------------------------------------
    # Representation (legacy field names)
    # -------------------------------------------------------------------------

    def to_representation(self, instance: ProjectEOT) -> dict:
        pd = self._schedule_row(instance)
        data = {
            "id": instance.id,
            "project_name": instance.project.name if instance.project_id else "",
            "date_type": (
                pd.date_type if pd else ProjectDates.DATE_TYPE_SCL
            ),
            "contractor_id": pd.contractor_id if pd else None,
            "contractor_name": pd.contractor_name if pd else None,
            "contractor": self.get_contractor(instance),
            "project_start": (
                pd.project_start.isoformat()
                if pd and pd.project_start
                else None
            ),
            # Legacy aliases for stored EOT dates
            "contract_finish": (
                instance.original_completion_date.isoformat()
                if instance.original_completion_date
                else None
            ),
            "forecast_finish": (
                pd.forecast_finish.isoformat()
                if pd and pd.forecast_finish
                else None
            ),
            "eot_date": (
                instance.revised_completion_date.isoformat()
                if instance.revised_completion_date
                else None
            ),
            "elapsed_duration": self.get_elapsed_duration(instance),
            "remaining_duration": self.get_remaining_duration(instance),
            "forecast_finish_duration": self.get_forecast_finish_duration(instance),
            "eot_duration": self.get_eot_duration(instance),
            "delay_days": self.get_delay_days(instance),
            "eot_delay_days": self.get_eot_delay_days(instance),
            "current_delay": self.get_current_delay(instance),
            # Additive EOT fields
            "eot_number": instance.eot_number,
            "extension_days": instance.extension_days,
            "reason": instance.reason,
            "remarks": instance.remarks or "",
            "status": instance.status,
            "approval_date": (
                instance.approval_date.isoformat() if instance.approval_date else None
            ),
            "supporting_document": (
                instance.supporting_document.name
                if instance.supporting_document
                else None
            ),
            "supporting_document_url": self.get_supporting_document_url(instance),
            "is_active": instance.is_active,
            "created_by": instance.created_by_id,
            "created_by_name": self.get_created_by_name(instance),
            "updated_by": instance.updated_by_id,
            "updated_by_name": self.get_updated_by_name(instance),
            "created_at": instance.created_at.isoformat() if instance.created_at else None,
            "updated_at": instance.updated_at.isoformat() if instance.updated_at else None,
        }
        return data

    # -------------------------------------------------------------------------
    # Validation / create / update
    # -------------------------------------------------------------------------

    def validate(self, attrs: dict) -> dict:
        request = self.context.get("request")
        raw = getattr(request, "data", {}) if request else {}

        # Merge raw keys not captured when using Serializer (multipart/json)
        for key in (
            "project_name",
            "date_type",
            "contractor_id",
            "contractor_name",
            "project_start",
            "contract_finish",
            "forecast_finish",
            "eot_date",
            "extension_days",
            "reason",
            "remarks",
            "status",
            "approval_date",
            "eot_number",
            "is_active",
        ):
            if key not in attrs and key in raw and raw.get(key) not in (None, ""):
                attrs[key] = raw.get(key)

        # Normalize date fields (may arrive as strings from raw merge)
        for key in (
            "project_start",
            "contract_finish",
            "forecast_finish",
            "eot_date",
            "approval_date",
        ):
            if key in attrs:
                attrs[key] = self._as_date(attrs[key])

        project_name = str(attrs.get("project_name") or "").strip()
        if not project_name:
            if self.instance is not None:
                project = self.instance.project
            else:
                raise serializers.ValidationError(
                    {"project_name": "project_name is required."}
                )
        else:
            project = resolve_project_for_module(project_name)
        attrs["_project"] = project

        date_type = attrs.get("date_type") or ProjectDates.DATE_TYPE_SCL
        attrs["date_type"] = date_type

        # Resolve optional schedule row (for context / link)
        schedule = None
        if date_type == ProjectDates.DATE_TYPE_SCL:
            schedule = (
                ProjectDates.objects.filter(
                    project=project, date_type=ProjectDates.DATE_TYPE_SCL
                )
                .order_by("id")
                .first()
            )
        else:
            contractor_id = attrs.get("contractor_id")
            contractor_name = attrs.get("contractor_name")
            try:
                contractor = resolve_contractor_for_write(
                    project,
                    contractor_id=contractor_id,
                    contractor_name=contractor_name,
                )
                schedule = ProjectDates.objects.filter(
                    project=project,
                    date_type=ProjectDates.DATE_TYPE_CONTRACTOR,
                    contractor_id=contractor.id,
                ).first()
            except Exception:
                schedule = None
        attrs["_schedule"] = schedule

        # ---- Map legacy dates → internal EOT columns ----
        contract_finish = attrs.get("contract_finish")
        if contract_finish is None and schedule:
            contract_finish = schedule.contract_finish
        if contract_finish is None and self.instance is None:
            contract_finish = original_completion_for_project(project)
        if contract_finish is None and self.instance is not None:
            contract_finish = self.instance.original_completion_date

        eot_date = attrs.get("eot_date")
        extension_days = attrs.get("extension_days")
        if extension_days is not None:
            try:
                extension_days = int(extension_days)
            except (TypeError, ValueError):
                raise serializers.ValidationError(
                    {"extension_days": "extension_days must be a positive integer."}
                )
            if extension_days <= 0:
                raise serializers.ValidationError(
                    {"extension_days": "extension_days must be greater than 0."}
                )

        if eot_date is None and contract_finish and extension_days:
            eot_date = compute_revised_date(contract_finish, extension_days)
        if eot_date is None and self.instance is not None:
            eot_date = self.instance.revised_completion_date

        if extension_days is None and contract_finish and eot_date:
            extension_days = (eot_date - contract_finish).days
            if extension_days <= 0:
                raise serializers.ValidationError(
                    {
                        "eot_date": (
                            "eot_date must be on or after contract_finish. "
                            f"Got contract_finish={contract_finish}, eot_date={eot_date}."
                        )
                    }
                )

        if self.instance is None:
            if not eot_date and not extension_days:
                raise serializers.ValidationError(
                    {"eot_date": "eot_date is required (or provide extension_days)."}
                )
            if not contract_finish:
                raise serializers.ValidationError(
                    {"contract_finish": "contract_finish is required."}
                )
            reason = str(attrs.get("reason") or "").strip()
            if not reason:
                raise serializers.ValidationError({"reason": "reason is required."})
            attrs["reason"] = reason

        if contract_finish and eot_date and contract_finish > eot_date:
            raise serializers.ValidationError(
                {
                    "eot_date": (
                        "eot_date must be on or after contract_finish. "
                        f"Got contract_finish={contract_finish}, eot_date={eot_date}."
                    )
                }
            )

        status_val = attrs.get(
            "status",
            getattr(self.instance, "status", ProjectEOT.STATUS_PENDING)
            if self.instance
            else ProjectEOT.STATUS_PENDING,
        )
        approval_date = attrs.get(
            "approval_date",
            getattr(self.instance, "approval_date", None) if self.instance else None,
        )
        if status_val == ProjectEOT.STATUS_APPROVED and not approval_date:
            raise serializers.ValidationError(
                {"approval_date": "approval_date is required when status is approved."}
            )

        # Fill derived internals for create/update
        if contract_finish is not None:
            attrs["_original_completion_date"] = contract_finish
        if eot_date is not None:
            attrs["_revised_completion_date"] = eot_date
        if extension_days is not None:
            attrs["extension_days"] = extension_days
        elif (
            attrs.get("_original_completion_date")
            and attrs.get("_revised_completion_date")
        ):
            attrs["extension_days"] = (
                attrs["_revised_completion_date"] - attrs["_original_completion_date"]
            ).days

        eot_number = attrs.get("eot_number")
        if eot_number is None and self.instance is None:
            eot_number = next_eot_number(project)
            attrs["eot_number"] = eot_number
        if eot_number is not None:
            qs = ProjectEOT.objects.filter(
                project=project, eot_number=eot_number, is_active=True
            )
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    {
                        "eot_number": (
                            f"EOT number {eot_number} already exists for this project."
                        )
                    }
                )

        if attrs.get("is_active") is False and self.instance is None:
            raise serializers.ValidationError(
                {"is_active": "Cannot create an inactive EOT."}
            )

        # Optional: accept project_start / forecast_finish only for validation context
        project_start = attrs.get("project_start")
        if project_start is None and schedule:
            project_start = schedule.project_start
        if project_start and contract_finish and project_start > contract_finish:
            raise serializers.ValidationError(
                {
                    "project_start": (
                        "project_start must be on or before contract_finish. "
                        f"Got project_start={project_start}, "
                        f"contract_finish={contract_finish}."
                    )
                }
            )

        return attrs

    def create(self, validated_data):
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        project = validated_data.pop("_project")
        schedule = validated_data.pop("_schedule", None)
        original = validated_data.pop("_original_completion_date")
        revised = validated_data.pop("_revised_completion_date")

        # Strip legacy-only write keys
        for key in (
            "project_name",
            "date_type",
            "contractor_id",
            "contractor_name",
            "project_start",
            "contract_finish",
            "forecast_finish",
            "eot_date",
            "contractor",
        ):
            validated_data.pop(key, None)

        instance = ProjectEOT(
            project=project,
            project_dates=schedule,
            eot_number=validated_data.get("eot_number") or next_eot_number(project),
            extension_days=validated_data["extension_days"],
            original_completion_date=original,
            revised_completion_date=revised,
            approval_date=validated_data.get("approval_date"),
            reason=validated_data.get("reason") or "",
            remarks=validated_data.get("remarks") or "",
            status=validated_data.get("status") or ProjectEOT.STATUS_PENDING,
            supporting_document=validated_data.get("supporting_document"),
            is_active=validated_data.get("is_active", True),
            created_by=user if user and user.is_authenticated else None,
            updated_by=user if user and user.is_authenticated else None,
        )
        instance.save()
        return instance

    def update(self, instance, validated_data):
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None

        schedule = validated_data.pop("_schedule", None)
        validated_data.pop("_project", None)
        original = validated_data.pop(
            "_original_completion_date", instance.original_completion_date
        )
        revised = validated_data.pop(
            "_revised_completion_date", instance.revised_completion_date
        )

        for key in (
            "project_name",
            "date_type",
            "contractor_id",
            "contractor_name",
            "project_start",
            "contract_finish",
            "forecast_finish",
            "eot_date",
            "contractor",
        ):
            validated_data.pop(key, None)

        if schedule is not None:
            instance.project_dates = schedule
        instance.original_completion_date = original
        instance.revised_completion_date = revised

        for field in (
            "eot_number",
            "extension_days",
            "approval_date",
            "reason",
            "remarks",
            "status",
            "supporting_document",
            "is_active",
        ):
            if field in validated_data and validated_data[field] is not None:
                setattr(instance, field, validated_data[field])

        if user and user.is_authenticated:
            instance.updated_by = user
        instance.save()
        return instance
