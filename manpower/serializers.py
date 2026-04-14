"""
Input: project_name, month_year (Jan-2023), manpower counts, hours, days.
Output MH and cumulatives computed in create(); not accepted from client.
"""

import re
from datetime import datetime
from functools import lru_cache

from django.db import IntegrityError, transaction
from rest_framework import serializers

from .models import ProjectManpower

# Jan = 1 … Dec = 12 for sorting
MONTH_YEAR_PATTERN = re.compile(r"^([A-Za-z]{3})-(\d{4})$")


@lru_cache(maxsize=128)
def parse_month_year(value: str) -> tuple[datetime, str]:
    """
    Parse "Jan-2023" → (datetime, canonical "Jan-2023").
    Month must be a valid 3-letter English abbreviation.
    """
    s = (value or "").strip()
    if not MONTH_YEAR_PATTERN.match(s):
        raise serializers.ValidationError(
            'month_year must look like "Jan-2023" (3-letter month, hyphen, 4-digit year).'
        )
    try:
        dt = datetime.strptime(s, "%b-%Y")
    except ValueError:
        try:
            dt = datetime.strptime(s.title(), "%b-%Y")
        except ValueError:
            raise serializers.ValidationError(
                "Invalid month or year in month_year (use e.g. Jan-2023)."
            )
    canonical = dt.strftime("%b-%Y")
    return dt, canonical


def month_year_sort_key(month_year: str) -> tuple[int, int]:
    """(year, month) for chronological sort."""
    _, canonical = parse_month_year(month_year)
    dt = datetime.strptime(canonical, "%b-%Y")
    return (dt.year, dt.month)


def dashboard_month_label(month_year: str) -> str:
    """Jan-2023 → Jan-23 for charts."""
    dt = datetime.strptime(parse_month_year(month_year)[1], "%b-%Y")
    return dt.strftime("%b-%y")


class ProjectManpowerInputSerializer(serializers.ModelSerializer):
    """POST body — no MH or cumulative fields."""

    class Meta:
        model = ProjectManpower
        fields = (
            "project_name",
            "month_year",
            "planned_manpower",
            "actual_manpower",
            "working_hours_per_day",
            "working_days_per_month",
        )

    def validate_month_year(self, value):
        _, canonical = parse_month_year(value)
        return canonical

    def validate_planned_manpower(self, v):
        if v < 0:
            raise serializers.ValidationError("Must be >= 0.")
        return v

    def validate_actual_manpower(self, v):
        if v < 0:
            raise serializers.ValidationError("Must be >= 0.")
        return v

    def validate_working_hours_per_day(self, v):
        if v is None or float(v) <= 0:
            raise serializers.ValidationError("Must be greater than 0.")
        return float(v)

    def validate_working_days_per_month(self, v):
        if v is None or int(v) <= 0:
            raise serializers.ValidationError("Must be greater than 0.")
        return int(v)

    def validate(self, attrs):
        attrs["project_name"] = (attrs.get("project_name") or "").strip()
        if not attrs["project_name"]:
            raise serializers.ValidationError(
                {"project_name": "This field may not be blank."}
            )
        return attrs

    def create(self, validated_data):
        pm = validated_data["planned_manpower"]
        am = validated_data["actual_manpower"]
        h = validated_data["working_hours_per_day"]
        d = validated_data["working_days_per_month"]

        planned_mh = round(pm * h * d, 4)
        actual_mh = round(am * h * d, 4)

        validated_data["planned_mh"] = planned_mh
        validated_data["actual_mh"] = actual_mh

        try:
            with transaction.atomic():
                instance = ProjectManpower.objects.create(**validated_data)
                ProjectManpower.recalculate_cumulatives(validated_data["project_name"])
                instance.refresh_from_db()
                return instance
        except IntegrityError:
            raise serializers.ValidationError(
                {"month_year": "This month_year already exists for this project."}
            )


class ProjectManpowerSerializer(serializers.ModelSerializer):
    manpower_efficiency = serializers.SerializerMethodField()
    actual_below_planned = serializers.SerializerMethodField()

    class Meta:
        model = ProjectManpower
        fields = (
            "id",
            "project_name",
            "month_year",
            "planned_manpower",
            "actual_manpower",
            "working_hours_per_day",
            "working_days_per_month",
            "planned_mh",
            "actual_mh",
            "planned_mh_cumulative",
            "actual_mh_cumulative",
            "manpower_efficiency",
            "actual_below_planned",
            "created_at",
        )
        read_only_fields = fields

    def get_manpower_efficiency(self, obj):
        if obj.planned_manpower == 0:
            return None
        return round(obj.actual_manpower / obj.planned_manpower, 4)

    def get_actual_below_planned(self, obj):
        return obj.actual_manpower < obj.planned_manpower
