"""
Equipment input: project_name, month (string or date), planned/actual only.
Cumulative fields are computed after save via ProjectEquipment.recalculate_cumulatives.
"""

from datetime import date, datetime
from functools import lru_cache

from django.db import IntegrityError, transaction
from rest_framework import serializers

from .models import ProjectEquipment


@lru_cache(maxsize=128)
def parse_month_to_first_day(value) -> date:
    """
    Accept Jan-23, Jan-2023, 2023-01-15, 2023-01 → first day of that month.
    """
    if isinstance(value, date):
        return value.replace(day=1)
    s = str(value).strip()
    for fmt in ("%b-%y", "%b-%Y", "%Y-%m-%d", "%Y-%m", "%d-%m-%Y", "%m/%Y", "%Y/%m"):
        try:
            dt = datetime.strptime(s, fmt)
            return date(dt.year, dt.month, 1)
        except ValueError:
            continue
    raise serializers.ValidationError(
        'Invalid month. Use e.g. "Jan-23", "2023-01", or "2023-01-01".'
    )


def month_label(d: date) -> str:
    """Dashboard-style label e.g. Jan-23."""
    return d.strftime("%b-%y")


class ProjectEquipmentInputSerializer(serializers.ModelSerializer):
    """Create payload — month as string; cumulatives not writable."""

    month = serializers.CharField(write_only=True)

    class Meta:
        model = ProjectEquipment
        fields = (
            "project_name",
            "month",
            "planned_equipment",
            "actual_equipment",
        )

    def validate_planned_equipment(self, v):
        if v < 0:
            raise serializers.ValidationError("Must be >= 0.")
        return v

    def validate_actual_equipment(self, v):
        if v < 0:
            raise serializers.ValidationError("Must be >= 0.")
        return v

    def validate(self, attrs):
        attrs["project_name"] = (attrs.get("project_name") or "").strip()
        if not attrs["project_name"]:
            raise serializers.ValidationError({"project_name": "This field may not be blank."})
        attrs["month"] = parse_month_to_first_day(attrs["month"])
        return attrs

    def create(self, validated_data):
        try:
            with transaction.atomic():
                instance = ProjectEquipment.objects.create(**validated_data)
                ProjectEquipment.recalculate_cumulatives(validated_data["project_name"])
                instance.refresh_from_db()
                return instance
        except IntegrityError:
            raise serializers.ValidationError(
                {"month": "This month already exists for this project. Each project may have only one row per month."}
            )


class ProjectEquipmentSerializer(serializers.ModelSerializer):
    """Full row for list/detail including optional efficiency metrics."""

    month_display = serializers.SerializerMethodField()
    equipment_efficiency = serializers.SerializerMethodField()
    actual_below_planned = serializers.SerializerMethodField()

    class Meta:
        model = ProjectEquipment
        fields = (
            "id",
            "project_name",
            "month",
            "month_display",
            "planned_equipment",
            "actual_equipment",
            "planned_cumulative",
            "actual_cumulative",
            "equipment_efficiency",
            "actual_below_planned",
            "created_at",
        )
        read_only_fields = fields

    def get_month_display(self, obj):
        return month_label(obj.month)

    def get_equipment_efficiency(self, obj):
        if obj.planned_equipment == 0:
            return None
        return round(obj.actual_equipment / obj.planned_equipment, 4)

    def get_actual_below_planned(self, obj):
        return obj.actual_equipment < obj.planned_equipment
