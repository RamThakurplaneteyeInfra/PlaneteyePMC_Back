"""
POST accepts monthly plan/actual cash flows and actual cost only.
All cumulative_* fields are computed after save.
"""

import re
from datetime import datetime

from django.db import IntegrityError
from rest_framework import serializers

from .models import CashFlow

MONTH_YEAR_PATTERN = re.compile(r"^([A-Za-z]{3})-(\d{4})$")


def parse_month_year(value: str) -> str:
    """Validate and return canonical month_year e.g. Jan-2023."""
    s = (value or "").strip()
    if not MONTH_YEAR_PATTERN.match(s):
        raise serializers.ValidationError(
            'month_year must look like "Jan-2023" (3-letter month, 4-digit year).'
        )
    try:
        dt = datetime.strptime(s, "%b-%Y")
    except ValueError:
        try:
            dt = datetime.strptime(s.title(), "%b-%Y")
        except ValueError:
            raise serializers.ValidationError("Invalid month or year.")
    return dt.strftime("%b-%Y")


def month_year_sort_key(month_year: str) -> tuple[int, int]:
    dt = datetime.strptime(month_year.strip(), "%b-%Y")
    return (dt.year, dt.month)


def dashboard_month_label(month_year: str) -> str:
    dt = datetime.strptime(month_year.strip(), "%b-%Y")
    return dt.strftime("%b-%y")


_NON_NEGATIVE_FLOAT_FIELDS = (
    "cash_in_monthly_plan",
    "cash_in_monthly_actual",
    "cash_out_monthly_plan",
    "cash_out_monthly_actual",
    "actual_cost_monthly",
)


class CashFlowInputSerializer(serializers.ModelSerializer):
    class Meta:
        model = CashFlow
        fields = (
            "project_name",
            "month_year",
            "cash_in_monthly_plan",
            "cash_in_monthly_actual",
            "cash_out_monthly_plan",
            "cash_out_monthly_actual",
            "actual_cost_monthly",
        )

    def validate_month_year(self, value):
        return parse_month_year(value)

    def validate(self, attrs):
        attrs["project_name"] = (attrs.get("project_name") or "").strip()
        if not attrs["project_name"]:
            raise serializers.ValidationError(
                {"project_name": "This field may not be blank."}
            )
        for fname in _NON_NEGATIVE_FLOAT_FIELDS:
            v = attrs.get(fname)
            if v is None:
                continue
            if float(v) < 0:
                raise serializers.ValidationError(
                    {fname: "Must be greater than or equal to 0."}
                )
            attrs[fname] = float(v)

        if CashFlow.objects.filter(
            project_name=attrs["project_name"],
            month_year=attrs["month_year"],
        ).exists():
            raise serializers.ValidationError(
                {"month_year": "This month_year already exists for this project."}
            )
        return attrs

    def create(self, validated_data):
        validated_data.setdefault("cash_in_cumulative_plan", 0)
        validated_data.setdefault("cash_in_cumulative_actual", 0)
        validated_data.setdefault("cash_out_cumulative_plan", 0)
        validated_data.setdefault("cash_out_cumulative_actual", 0)
        validated_data.setdefault("actual_cost_cumulative", 0)
        try:
            instance = CashFlow.objects.create(**validated_data)
        except IntegrityError:
            raise serializers.ValidationError(
                {"month_year": "This month_year already exists for this project."}
            )
        CashFlow.recalculate_cumulatives(validated_data["project_name"])
        instance.refresh_from_db()
        return instance


class CashFlowSerializer(serializers.ModelSerializer):
    """Full row including cumulatives and optional derived flags."""

    profit_actual_net = serializers.SerializerMethodField()
    cash_out_exceeds_cash_in_actual = serializers.SerializerMethodField()

    class Meta:
        model = CashFlow
        fields = (
            "id",
            "project_name",
            "month_year",
            "cash_in_monthly_plan",
            "cash_in_monthly_actual",
            "cash_out_monthly_plan",
            "cash_out_monthly_actual",
            "actual_cost_monthly",
            "cash_in_cumulative_plan",
            "cash_in_cumulative_actual",
            "cash_out_cumulative_plan",
            "cash_out_cumulative_actual",
            "actual_cost_cumulative",
            "profit_actual_net",
            "cash_out_exceeds_cash_in_actual",
            "created_at",
        )
        read_only_fields = fields

    def get_profit_actual_net(self, obj):
        """Cumulative actual cash-in minus cumulative actual cash-out (same month end)."""
        return round(
            obj.cash_in_cumulative_actual - obj.cash_out_cumulative_actual,
            4,
        )

    def get_cash_out_exceeds_cash_in_actual(self, obj):
        return obj.cash_out_monthly_actual > obj.cash_in_monthly_actual
