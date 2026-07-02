"""
Contract Value Serializer.

Writable: project_name, contract_type, contractor_id, original_contract_value, excess_value, saving
Computed (read-only): revised_value, increase_percentage
Legacy aliases supported for backward compatibility.
"""

from decimal import Decimal

from rest_framework import serializers

from contractors.resolvers import contractor_payload, resolve_contractor_for_write
from projects.models import Project

from ..models.contract_value import ContractValue
from .contract_value_metrics import metrics_from_record


def _normalize_contract_type(value: str) -> str:
    if not value:
        return value
    normalized = value.strip().upper()
    if normalized == "CONTRACTOR":
        return ContractValue.ContractType.CONTRACTOR
    if normalized == "SCL":
        return ContractValue.ContractType.SCL
    return value.strip()


class ContractValueSerializer(serializers.ModelSerializer):
    revised_value = serializers.SerializerMethodField()
    increase_percentage = serializers.SerializerMethodField()
    contractor = serializers.SerializerMethodField()
    contractor_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)

    projectName = serializers.SerializerMethodField()
    contractType = serializers.SerializerMethodField()
    originalContractValue = serializers.SerializerMethodField()
    excessValue = serializers.SerializerMethodField()
    revisedContractValue = serializers.SerializerMethodField()
    approvedVOPercentage = serializers.SerializerMethodField()

    class Meta:
        model = ContractValue
        fields = [
            "id",
            "project_name",
            "projectName",
            "contract_type",
            "contractType",
            "contractor_name",
            "contractor",
            "contractor_id",
            "original_contract_value",
            "originalContractValue",
            "excess_value",
            "excessValue",
            "saving",
            "revised_value",
            "increase_percentage",
            "revisedContractValue",
            "approvedVOPercentage",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "projectName",
            "contractType",
            "contractor",
            "originalContractValue",
            "excessValue",
            "revised_value",
            "increase_percentage",
            "revisedContractValue",
            "approvedVOPercentage",
            "created_at",
            "updated_at",
        ]

    def get_contractor(self, obj):
        return contractor_payload(obj.contractor)

    def get_projectName(self, obj) -> str:
        return obj.project_name

    def get_contractType(self, obj) -> str:
        return obj.contract_type

    def get_originalContractValue(self, obj):
        return obj.original_contract_value

    def get_excessValue(self, obj):
        return obj.excess_value

    def get_revised_value(self, obj) -> Decimal:
        return metrics_from_record(obj)["revised_value"]

    def get_increase_percentage(self, obj) -> Decimal:
        return metrics_from_record(obj)["increase_percentage"]

    def get_revisedContractValue(self, obj) -> Decimal:
        return self.get_revised_value(obj)

    def get_approvedVOPercentage(self, obj) -> Decimal:
        return self.get_increase_percentage(obj)

    def to_internal_value(self, data):
        if hasattr(data, "copy"):
            data = data.copy()
        else:
            data = dict(data)

        if "projectName" in data and "project_name" not in data:
            data["project_name"] = data["projectName"]
        if "contractType" in data and "contract_type" not in data:
            data["contract_type"] = data["contractType"]
        if "contractorName" in data and "contractor_name" not in data:
            data["contractor_name"] = data["contractorName"]

        if "originalContractValue" in data and "original_contract_value" not in data:
            data["original_contract_value"] = data["originalContractValue"]
        if "excessValue" in data and "excess_value" not in data:
            data["excess_value"] = data["excessValue"]
        if "approvedVO" in data and "excess_value" not in data:
            data["excess_value"] = data["approvedVO"]
        if "potentialPendingVO" in data and "saving" not in data:
            data["saving"] = data["potentialPendingVO"]

        if "contract_type" in data:
            data["contract_type"] = _normalize_contract_type(str(data["contract_type"]))

        return super().to_internal_value(data)

    def validate_project_name(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("project_name cannot be blank.")
        return value

    def validate_contract_type(self, value: str) -> str:
        value = _normalize_contract_type(value)
        allowed = {
            ContractValue.ContractType.SCL,
            ContractValue.ContractType.CONTRACTOR,
        }
        if value not in allowed:
            raise serializers.ValidationError(
                "contract_type must be SCL or CONTRACTOR."
            )
        return value

    def validate_contractor_name(self, value: str):
        if value is None:
            return value
        return str(value).strip()

    def validate(self, attrs):
        project_name = attrs.get("project_name") or (
            self.instance.project_name if self.instance else None
        )
        contract_type = attrs.get(
            "contract_type",
            getattr(self.instance, "contract_type", None) if self.instance else None,
        )
        contractor_id = attrs.pop("contractor_id", None)
        if contractor_id is None and hasattr(self, "initial_data"):
            contractor_id = self.initial_data.get("contractor_id")
        contractor_name = attrs.get(
            "contractor_name",
            getattr(self.instance, "contractor_name", None) if self.instance else None,
        )

        if contract_type == ContractValue.ContractType.SCL:
            attrs["contractor"] = None
            attrs["contractor_name"] = None
        elif contract_type == ContractValue.ContractType.CONTRACTOR:
            project = Project.objects.filter(name__iexact=str(project_name).strip()).first()
            if project is None:
                raise serializers.ValidationError(
                    {"project_name": f"No project found with name '{project_name}'."}
                )
            contractor = resolve_contractor_for_write(
                project,
                contractor_id=contractor_id,
                contractor_name=contractor_name,
            )
            attrs["contractor"] = contractor
            attrs["contractor_name"] = contractor.contractor_name

        return attrs

    def _validate_non_negative(self, value, field_name: str) -> Decimal:
        if value is not None and value < 0:
            raise serializers.ValidationError(f"{field_name} must be >= 0.")
        return value if value is not None else Decimal("0.00")

    def validate_original_contract_value(self, value):
        return self._validate_non_negative(value, "original_contract_value")

    def validate_excess_value(self, value):
        return self._validate_non_negative(value, "excess_value")

    def validate_saving(self, value):
        return self._validate_non_negative(value, "saving")
