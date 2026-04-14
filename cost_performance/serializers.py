import re
from datetime import datetime
from decimal import Decimal
from functools import lru_cache

from django.db import IntegrityError
from rest_framework import serializers

from .models import ProjectCostPerformance
from projects.models import Project

MONTH_YEAR_PATTERN = re.compile(r"^([A-Za-z]+)-(\d{4})$")

@lru_cache(maxsize=128)
def _parse_flexible_month_year_cached(s: str) -> datetime:
    """Cached version of month-year parsing for performance."""
    s = s.title()
    try:
        return datetime.strptime(s, "%b-%Y")
    except ValueError:
        try:
            return datetime.strptime(s, "%B-%Y")
        except ValueError:
            raise ValueError(f"Invalid month or year in '{s}'.")


def _parse_flexible_month_year(s: str) -> datetime:
    """Parse month-year with caching for performance."""
    return _parse_flexible_month_year_cached(s)


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


@lru_cache(maxsize=128)
def month_year_sort_key(month_year: str) -> tuple[int, int]:
    try:
        dt = _parse_flexible_month_year(month_year.strip())
        return (dt.year, dt.month)
    except ValueError:
        return (0, 0)


@lru_cache(maxsize=128)
def dashboard_month_label(month_year: str) -> str:
    try:
        dt = _parse_flexible_month_year(month_year.strip())
        return dt.strftime("%b-%y")
    except ValueError:
        return month_year.strip()[:6]


class ProjectCostPerformanceInputSerializer(serializers.ModelSerializer):
    """POST: bcws, bcwp, acwp, fcst; optional bac for VAC. No eac/cv/sv/cpi/vac."""

    bac = serializers.DecimalField(max_digits=18, decimal_places=4, required=False, allow_null=True)
    project_name = serializers.CharField(write_only=True, required=True)  # For backward compatibility
    project = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = ProjectCostPerformance
        fields = (
            "project_name",
            "project",
            "month_year",
            "bcws",
            "bcwp",
            "acwp",
            "fcst",
            "bac",
        )

    def validate_month_year(self, value):
        return parse_month_year(value)

    def _validate_non_negative_decimal(self, value, field_name):
        """
        Validate that a decimal value is non-negative.
        Returns default Decimal("0") if None, otherwise validates >= 0.
        """
        if value is None:
            return Decimal("0")
        if value < 0:
            raise serializers.ValidationError({field_name: "Must be >= 0."})
        return value

    def validate(self, attrs):
        # Normalize project_name once
        project_name = (attrs.get("project_name") or "").strip()
        if not project_name:
            raise serializers.ValidationError({"project_name": "Required."})

        # Get or create project using get_or_create for efficiency
        project, created = Project.objects.get_or_create(
            name=project_name,
            defaults={'budget': Decimal('0')}
        )
        attrs["project"] = project

        # Keep project_name for backward compatibility
        attrs["project_name"] = project_name

        # Validate all financial fields using Decimal (no float conversions)
        # ACWP >= 0
        acwp = attrs.get("acwp")
        if acwp is not None and acwp < 0:
            raise serializers.ValidationError({"acwp": "Must be >= 0."})

        # FCST >= 0
        fcst = attrs.get("fcst")
        if fcst is not None and fcst < 0:
            raise serializers.ValidationError({"fcst": "Must be >= 0."})

        # BAC > 0 if provided
        bac = attrs.get("bac")
        if bac is not None and bac <= 0:
            raise serializers.ValidationError({"bac": "Must be greater than 0."})

        # BCWS and BCWP >= 0 using helper method
        attrs["bcws"] = self._validate_non_negative_decimal(attrs.get("bcws"), "bcws")
        attrs["bcwp"] = self._validate_non_negative_decimal(attrs.get("bcwp"), "bcwp")

        # Remove redundant .exists() check - rely on database constraint
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
    project_name = serializers.CharField(source='project.name', read_only=True)

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
    bcws = serializers.DecimalField(max_digits=18, decimal_places=4, required=False, default=0, help_text="Budgeted Cost of Work Scheduled")
    percent_complete = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, default=None, min_value=0, max_value=100, help_text="Percentage complete (0-100)")
    bcwp = serializers.DecimalField(max_digits=18, decimal_places=4, required=False, default=None, help_text="Budgeted Cost of Work Performed (earned value)")
    ac = serializers.DecimalField(max_digits=18, decimal_places=4, required=False, default=0, help_text="Actual Cost")


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
    bac = serializers.DecimalField(max_digits=18, decimal_places=4, required=True, min_value=0, help_text="Budget at Completion")
    monthly_data = serializers.ListField(
        child=MonthlyDataInputSerializer(),
        allow_empty=False,
        help_text="Array of monthly data points"
    )


class MonthlyDataOutputSerializer(serializers.Serializer):
    """Serializer for monthly data in dashboard output."""
    month = serializers.CharField()
    bcws = serializers.DecimalField(max_digits=18, decimal_places=4)
    bcwp = serializers.DecimalField(max_digits=18, decimal_places=4)
    ac = serializers.DecimalField(max_digits=18, decimal_places=4)
    cv = serializers.DecimalField(max_digits=18, decimal_places=4)
    cpi = serializers.DecimalField(max_digits=10, decimal_places=6, allow_null=True)
    status = serializers.CharField()
    fcst = serializers.DecimalField(max_digits=18, decimal_places=4, allow_null=True)


class CumulativeDataOutputSerializer(serializers.Serializer):
    """Serializer for cumulative data in dashboard output."""
    month = serializers.CharField()
    cumulative_bcws = serializers.DecimalField(max_digits=18, decimal_places=4)
    cumulative_bcwp = serializers.DecimalField(max_digits=18, decimal_places=4)
    cumulative_ac = serializers.DecimalField(max_digits=18, decimal_places=4)
    cumulative_cv = serializers.DecimalField(max_digits=18, decimal_places=4)
    cumulative_cpi = serializers.DecimalField(max_digits=10, decimal_places=6, allow_null=True)


class EVMSummarySerializer(serializers.Serializer):
    """Serializer for EVM summary section."""
    bcwp = serializers.DecimalField(max_digits=18, decimal_places=4, help_text="Earned Value (Budgeted Cost of Work Performed)")
    ac = serializers.DecimalField(max_digits=18, decimal_places=4, help_text="Actual Cost")
    cv = serializers.DecimalField(max_digits=18, decimal_places=4, help_text="Cost Variance (BCWP - AC)")
    cpi = serializers.DecimalField(max_digits=10, decimal_places=6, allow_null=True, help_text="Cost Performance Index")
    status = serializers.CharField(help_text="Budget status: under_budget, on_budget, or over_budget")
    eac = serializers.DecimalField(max_digits=18, decimal_places=4, help_text="Estimate at Completion (BAC / CPI)")
    etc = serializers.DecimalField(max_digits=18, decimal_places=4, help_text="Estimate to Complete (EAC - AC)")


class EVMDashboardOutputSerializer(serializers.Serializer):
    """Serializer for complete EVM dashboard output."""
    summary = EVMSummarySerializer()
    monthly = MonthlyDataOutputSerializer(many=True)
    cumulative = CumulativeDataOutputSerializer(many=True)
