"""
POST accepts monthly plan/actual cash flows and actual cost only.
All cumulative_* fields are computed after save.
"""

import re
from datetime import datetime
from decimal import Decimal
from functools import lru_cache

from django.db import IntegrityError, transaction
from rest_framework import serializers

from .models import CashFlow

MONTH_YEAR_PATTERN = re.compile(r"^([A-Za-z]{3})-(\d{4})$")


@lru_cache(maxsize=128)
def _parse_month_year_cached(value: str) -> datetime:
    """Cached datetime parsing for performance."""
    return datetime.strptime(value, "%b-%Y")


def parse_month_year(value: str) -> str:
    """Validate and return canonical month_year e.g. Jan-2023."""
    s = (value or "").strip()
    if not MONTH_YEAR_PATTERN.match(s):
        raise serializers.ValidationError(
            'month_year must look like "Jan-2023" (3-letter month, 4-digit year).'
        )
    try:
        dt = _parse_month_year_cached(s)
    except ValueError:
        try:
            dt = _parse_month_year_cached(s.title())
        except ValueError:
            raise serializers.ValidationError("Invalid month or year.")
    return dt.strftime("%b-%Y")


@lru_cache(maxsize=128)
def month_year_sort_key(month_year: str) -> tuple[int, int]:
    dt = _parse_month_year_cached(month_year.strip())
    return (dt.year, dt.month)


@lru_cache(maxsize=128)
def dashboard_month_label(month_year: str) -> str:
    dt = _parse_month_year_cached(month_year.strip())
    return dt.strftime("%b-%y")


_NON_NEGATIVE_DECIMAL_FIELDS = (
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
        for fname in _NON_NEGATIVE_DECIMAL_FIELDS:
            v = attrs.get(fname)
            if v is None:
                continue
            # Keep as Decimal for precision, don't convert to float
            try:
                decimal_value = Decimal(str(v))
            except (ValueError, TypeError):
                raise serializers.ValidationError(
                    {fname: "Must be a valid number."}
                )
            if decimal_value < 0:
                raise serializers.ValidationError(
                    {fname: "Must be greater than or equal to 0."}
                )
            # Keep the Decimal value instead of converting to float
            attrs[fname] = decimal_value

        # Remove redundant .exists() check - rely on database constraint
        return attrs

    def create(self, validated_data):
        # Remove unnecessary defaults since model provides them
        try:
            instance = CashFlow.objects.create(**validated_data)
        except IntegrityError:
            raise serializers.ValidationError(
                {"month_year": "This month_year already exists for this project."}
            )

        # Use transaction.on_commit to defer recalculation until after DB commit
        def recalculate_after_commit():
            CashFlow.recalculate_cumulatives(validated_data["project_name"])

        transaction.on_commit(recalculate_after_commit)

        # Remove refresh_from_db() - not needed since we don't modify the instance after creation
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
        """
        Cumulative actual cash-in minus cumulative actual cash-out (same month end).
        Values are already stored with 4 decimal places, so no additional rounding needed.
        """
        # Since cumulative fields are stored as Decimal with 4 decimal places,
        # the subtraction result maintains precision without additional rounding
        return obj.cash_in_cumulative_actual - obj.cash_out_cumulative_actual

    def get_cash_out_exceeds_cash_in_actual(self, obj):
        return obj.cash_out_monthly_actual > obj.cash_in_monthly_actual
