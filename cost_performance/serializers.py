import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from django.db import IntegrityError
from rest_framework import serializers

from .models import ProjectCostPerformance

MONTH_YEAR_PATTERN = re.compile(r"^([A-Za-z]+)-(\d{4})$")

def _parse_flexible_month_year(s: str) -> datetime:
    s = s.title()
    try:
        return datetime.strptime(s, "%b-%Y")
    except ValueError:
        try:
            return datetime.strptime(s, "%B-%Y")
        except ValueError:
            raise ValueError(f"Invalid month or year in '{s}'.")

def parse_month_year(value: str) -> str:
    s = (value or "").strip()
    if not MONTH_YEAR_PATTERN.match(s):
        raise serializers.ValidationError(
            'month_year must look like "Jan-2023" or "January-2023".'
        )
    try:
        dt = _parse_flexible_month_year(s)
    except ValueError:
        raise serializers.ValidationError("Invalid month or year.")
    return dt.strftime("%b-%Y")


def month_year_sort_key(month_year: str) -> tuple[int, int]:
    try:
        dt = _parse_flexible_month_year(month_year.strip())
        return (dt.year, dt.month)
    except ValueError:
        return (0, 0)


def dashboard_month_label(month_year: str) -> str:
    try:
        dt = _parse_flexible_month_year(month_year.strip())
        return dt.strftime("%b-%y")
    except ValueError:
        return month_year.strip()[:6]


class ProjectCostPerformanceInputSerializer(serializers.ModelSerializer):
    """POST: bcws, bcwp, acwp, fcst; optional bac for VAC. No eac/cv/sv/cpi/vac."""

    bac = serializers.FloatField(required=False, allow_null=True)

    class Meta:
        model = ProjectCostPerformance
        fields = (
            "project_name",
            "month_year",
            "bcws",
            "bcwp",
            "acwp",
            "fcst",
            "bac",
        )

    def validate_month_year(self, value):
        return parse_month_year(value)

    def _non_negative(self, attrs, *names):
        for n in names:
            v = attrs.get(n)
            if v is None:
                continue
            if float(v) < 0:
                raise serializers.ValidationError({n: "Must be >= 0."})
            attrs[n] = float(v)

    def validate(self, attrs):
        attrs["project_name"] = (attrs.get("project_name") or "").strip()
        if not attrs["project_name"]:
            raise serializers.ValidationError({"project_name": "Required."})
        
        # Validate ACWP >= 0
        acwp = attrs.get("acwp")
        if acwp is not None and float(acwp) < 0:
            raise serializers.ValidationError({"acwp": "Must be >= 0."})
        
        # Validate FCST >= 0
        fcst = attrs.get("fcst")
        if fcst is not None and float(fcst) < 0:
            raise serializers.ValidationError({"fcst": "Must be >= 0."})
        
        # Validate BAC > 0 (if provided)
        bac = attrs.get("bac")
        if bac is not None:
            if float(bac) <= 0:
                raise serializers.ValidationError({"bac": "Must be greater than 0."})
        
        # Validate other non-negative fields
        self._non_negative(attrs, "bcws", "bcwp")

        if ProjectCostPerformance.objects.filter(
            project_name=attrs["project_name"],
            month_year=attrs["month_year"],
        ).exists():
            raise serializers.ValidationError(
                {"month_year": "Already exists for this project."}
            )
        return attrs

    def create(self, validated_data):
        # Remove any pre-calculated values - let the model's save() method
        # handle all calculations to ensure consistency
        validated_data.pop("eac", None)
        validated_data.pop("cv", None)
        validated_data.pop("sv", None)
        validated_data.pop("cpi", None)
        validated_data.pop("vac", None)

        try:
            return ProjectCostPerformance.objects.create(**validated_data)
        except IntegrityError:
            raise serializers.ValidationError(
                {"month_year": "Already exists for this project."}
            )


class ProjectCostPerformanceSerializer(serializers.ModelSerializer):
    over_budget_cost = serializers.SerializerMethodField()
    behind_schedule = serializers.SerializerMethodField()

    class Meta:
        model = ProjectCostPerformance
        fields = (
            "id",
            "project_name",
            "month_year",
            "bcws",
            "bcwp",
            "acwp",
            "fcst",
            "bac",
            "eac",
            "cv",
            "sv",
            "cpi",
            "vac",
            "over_budget_cost",
            "behind_schedule",
            "created_at",
        )
        read_only_fields = fields

    def get_over_budget_cost(self, obj):
        return obj.cv < 0

    def get_behind_schedule(self, obj):
        return obj.sv < 0


# ========================================
# EVM Dashboard Serializers (New Format)
# ========================================

class MonthlyDataInputSerializer(serializers.Serializer):
    """Serializer for monthly data in EVM dashboard input."""
    month = serializers.CharField(max_length=12, help_text="Month-Year (e.g., 'Jan-2022')")
    bcws = serializers.FloatField(required=False, default=0, help_text="Budgeted Cost of Work Scheduled")
    percent_complete = serializers.FloatField(required=False, default=None, min_value=0, max_value=100, help_text="Percentage complete (0-100)")
    bcwp = serializers.FloatField(required=False, default=None, help_text="Budgeted Cost of Work Performed (earned value)")
    ac = serializers.FloatField(required=False, default=0, help_text="Actual Cost")

    def validate(self, attrs):
        # Must have either percent_complete or bcwp
        percent_complete = attrs.get('percent_complete')
        bcwp = attrs.get('bcwp')
        
        if percent_complete is None and bcwp is None:
            raise serializers.ValidationError(
                "Either 'percent_complete' or 'bcwp' must be provided."
            )
        return attrs


class EVMDashboardInputSerializer(serializers.Serializer):
    """Serializer for EVM dashboard bulk input.
    
    Expected format:
    {
        "project_name": "Project Alpha",
        "bac": 1000000,
        "monthlyData": [
            {
                "month": "Jan-2022",
                "bcws": 100000,
                "percentComplete": 50,  // optional if bcwp given
                "bcwp": 50000,          // optional if percentComplete given
                "ac": 55000
            }
        ]
    }
    """
    project_name = serializers.CharField(max_length=255, help_text="Project name")
    bac = serializers.FloatField(required=True, min_value=0, help_text="Budget at Completion")
    monthly_data = serializers.ListField(
        child=MonthlyDataInputSerializer(),
        allow_empty=False,
        help_text="Array of monthly data points"
    )

    def validate_monthly_data(self, value):
        if not value:
            raise serializers.ValidationError("At least one monthly data point is required.")
        return value


class MonthlyDataOutputSerializer(serializers.Serializer):
    """Serializer for monthly data in dashboard output."""
    month = serializers.CharField()
    bcws = serializers.FloatField()
    bcwp = serializers.FloatField()
    ac = serializers.FloatField()
    cv = serializers.FloatField()
    cpi = serializers.FloatField(allow_null=True)
    status = serializers.CharField()
    fcst = serializers.FloatField(allow_null=True)


class CumulativeDataOutputSerializer(serializers.Serializer):
    """Serializer for cumulative data in dashboard output."""
    month = serializers.CharField()
    cumulative_bcws = serializers.FloatField()
    cumulative_bcwp = serializers.FloatField()
    cumulative_ac = serializers.FloatField()
    cumulative_cv = serializers.FloatField()
    cumulative_cpi = serializers.FloatField(allow_null=True)


class EVMSummarySerializer(serializers.Serializer):
    """Serializer for EVM summary section."""
    bcwp = serializers.FloatField(help_text="Earned Value (Budgeted Cost of Work Performed)")
    ac = serializers.FloatField(help_text="Actual Cost")
    cv = serializers.FloatField(help_text="Cost Variance (BCWP - AC)")
    cpi = serializers.FloatField(allow_null=True, help_text="Cost Performance Index")
    status = serializers.CharField(help_text="Budget status: under_budget, on_budget, or over_budget")
    eac = serializers.FloatField(help_text="Estimate at Completion (BAC / CPI)")
    etc = serializers.FloatField(help_text="Estimate to Complete (EAC - AC)")


class EVMDashboardOutputSerializer(serializers.Serializer):
    """Serializer for complete EVM dashboard output."""
    summary = EVMSummarySerializer()
    monthly = MonthlyDataOutputSerializer(many=True)
    cumulative = CumulativeDataOutputSerializer(many=True)
