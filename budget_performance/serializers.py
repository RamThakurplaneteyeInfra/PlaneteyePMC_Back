"""
Serializers for Budget vs Cost Performance.

Calculations (EVM):
  CPI = BCWP / ACWP
  EAC = BAC / CPI
  ETG = EAC - ACWP
  VAC = BAC - EAC
  CV  = BCWP - ACWP

Input accepts only project_name, budget_at_completion, earned_value, actual_cost.
Calculated fields are never taken from the client.

Internally uses ForeignKey to Project model for data integrity,
but API maintains backward compatibility.
"""

from decimal import Decimal, ROUND_HALF_UP

from rest_framework import serializers

from .models import BudgetCostPerformance
from projects.models import Project


def _to_decimal(value) -> Decimal:
    """Coerce numeric input to Decimal for stable money/math handling."""
    if value is None:
        raise serializers.ValidationError("This field is required.")
    try:
        return Decimal(str(value))
    except Exception:
        raise serializers.ValidationError("Enter a valid number.")


class BudgetCostPerformanceInputSerializer(serializers.Serializer):
    """
    POST body must include exactly these inputs (canonical names):

    - project_name
    - budget_at_completion  (BAC)
    - earned_value          (BCWP)
    - actual_cost           (ACWP)

    Aliases accepted: bac → budget_at_completion, bcwp → earned_value, acwp → actual_cost.
    """

    project_name = serializers.CharField(
        max_length=255,
        trim_whitespace=True,
        help_text="Project name",
    )
    budget_at_completion = serializers.DecimalField(
        max_digits=24,
        decimal_places=4,
        required=False,
        help_text="Budget at completion (BAC). Alias: bac",
    )
    earned_value = serializers.DecimalField(
        max_digits=24,
        decimal_places=4,
        required=False,
        min_value=0,
        help_text="Earned value (BCWP). Alias: bcwp",
    )
    actual_cost = serializers.DecimalField(
        max_digits=24,
        decimal_places=4,
        required=False,
        help_text="Actual cost (ACWP). Alias: acwp",
    )

    def to_internal_value(self, data):
        """Map bac/bcwp/acwp → budget_at_completion / earned_value / actual_cost if needed."""
        try:
            from django.http import QueryDict

            if isinstance(data, QueryDict):
                d = data.dict()
            else:
                d = dict(data)
        except (TypeError, ValueError):
            d = dict(data)

        if d.get("budget_at_completion") is None and d.get("bac") is not None:
            d["budget_at_completion"] = d["bac"]
        if d.get("earned_value") is None and d.get("bcwp") is not None:
            d["earned_value"] = d["bcwp"]
        if d.get("actual_cost") is None and d.get("acwp") is not None:
            d["actual_cost"] = d["acwp"]
        for k in ("bac", "bcwp", "acwp"):
            d.pop(k, None)

        return super().to_internal_value(d)

    def validate_project_name(self, value: str) -> str:
        if not value or not value.strip():
            raise serializers.ValidationError("project_name cannot be empty.")
        # Normalize project name: strip whitespace and title case for consistency
        return value.strip().title()

    def validate_budget_at_completion(self, value: Decimal) -> Decimal:
        if value <= 0:
            raise serializers.ValidationError(
                "budget_at_completion (BAC) must be greater than 0."
            )
        return value

    def validate_actual_cost(self, value: Decimal) -> Decimal:
        if value <= 0:
            raise serializers.ValidationError(
                "actual_cost (ACWP) must be greater than 0 (avoids division by zero for CPI)."
            )
        return value

    def validate_earned_value(self, value: Decimal) -> Decimal:
        return value

    def validate(self, attrs):
        missing = [
            f
            for f in ("budget_at_completion", "earned_value", "actual_cost")
            if attrs.get(f) is None
        ]
        if missing:
            raise serializers.ValidationError(
                {
                    "detail": (
                        "Required JSON fields: project_name, budget_at_completion, "
                        "earned_value, actual_cost."
                    ),
                    **{f: "This field is required." for f in missing},
                }
            )
        bcwp = attrs["earned_value"]
        if bcwp == 0:
            raise serializers.ValidationError(
                {
                    "earned_value": (
                        "earned_value (BCWP) must be greater than 0. "
                        "When BCWP is 0, CPI is 0 and EAC = BAC/CPI cannot be calculated."
                    )
                }
            )
        return attrs

    def create(self, validated_data):
        # Get or create project using normalized name
        project_name = validated_data["project_name"]
        project, created = Project.objects.get_or_create(
            name=project_name,
            defaults={'budget': Decimal('0.00')}
        )

        # All values are already Decimal from validation
        bac = validated_data["budget_at_completion"]
        bcwp = validated_data["earned_value"]
        acwp = validated_data["actual_cost"]

        # Perform calculations in Decimal for precision
        # CPI = BCWP / ACWP (ACWP > 0 and BCWP > 0 already enforced)
        cpi = (bcwp / acwp).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        # EAC = BAC / CPI
        eac = (bac / cpi).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        # ETG = EAC - ACWP
        etg = (eac - acwp).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        # VAC = BAC - EAC
        vac = (bac - eac).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        # CV = BCWP - ACWP
        cv = (bcwp - acwp).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

        return BudgetCostPerformance.objects.create(
            project_name=project_name,  # Keep for backward compatibility during transition
            project=project,  # New ForeignKey field
            bac=bac,
            bcwp=bcwp,
            acwp=acwp,
            cpi=cpi,
            eac=eac,
            etg=etg,
            vac=vac,
            cv=cv,
        )

    def update(self, instance, validated_data):
        raise NotImplementedError("Updates use a separate flow if needed.")


class BudgetCostPerformanceSerializer(serializers.ModelSerializer):
    """
    Dashboard/API response: matches required JSON keys (bac, bcwp, acwp, …).
    Returns project_name from ForeignKey for backward compatibility.
    """

    class Meta:
        model = BudgetCostPerformance
        fields = (
            "id",
            "project_name",
            "bac",
            "bcwp",
            "acwp",
            "cpi",
            "eac",
            "etg",
            "vac",
            "cv",
            "created_at",
        )
        read_only_fields = fields

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Return numeric types suitable for JSON dashboards
        # Convert Decimal to float only for final output
        out = {
            "project_name": data["project_name"],  # This comes from the CharField, not the ForeignKey
            "bac": float(data["bac"]),
            "bcwp": float(data["bcwp"]),
            "acwp": float(data["acwp"]),
            "cpi": float(data["cpi"]),
            "eac": float(data["eac"]),
            "etg": float(data["etg"]),
            "vac": float(data["vac"]),
            "cv": float(data["cv"]),
        }
        # Optional metadata for list/dashboard
        if "id" in data:
            out["id"] = data["id"]
        if "created_at" in data:
            out["created_at"] = data["created_at"]
        return out
