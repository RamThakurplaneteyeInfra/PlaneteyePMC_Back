"""
Invoicing Information Serializer.

Writable: project_name, invoice_type, gross_billed, gross_certified_billed
Computed: difference, certification_efficiency
"""

from decimal import Decimal

from rest_framework import serializers

from ..models.invoicing_information import InvoicingInformation
from .invoicing_metrics import metrics_from_record

_ZERO = Decimal("0.00")


def _normalize_invoice_type(value: str) -> str:
    if not value:
        return value
    normalized = value.strip().upper()
    if normalized == "PMC":
        return InvoicingInformation.InvoiceType.SCL
    if normalized == "CONTRACTOR":
        return InvoicingInformation.InvoiceType.CONTRACTOR
    if normalized == "SCL":
        return InvoicingInformation.InvoiceType.SCL
    return value.strip()


class InvoicingInformationSerializer(serializers.ModelSerializer):
    difference = serializers.SerializerMethodField()
    certification_efficiency = serializers.SerializerMethodField()

    # Legacy read aliases
    projectName = serializers.SerializerMethodField()
    invoiceType = serializers.SerializerMethodField()
    grossBilled = serializers.SerializerMethodField()
    grossCertifiedBilled = serializers.SerializerMethodField()
    netBilledWithoutVAT = serializers.SerializerMethodField()
    netCollected = serializers.SerializerMethodField()
    netDue = serializers.SerializerMethodField()

    class Meta:
        model = InvoicingInformation
        fields = [
            "id",
            "project_name",
            "projectName",
            "invoice_type",
            "invoiceType",
            "gross_billed",
            "grossBilled",
            "gross_certified_billed",
            "grossCertifiedBilled",
            "difference",
            "certification_efficiency",
            "netBilledWithoutVAT",
            "netCollected",
            "netDue",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "projectName",
            "invoiceType",
            "grossBilled",
            "grossCertifiedBilled",
            "difference",
            "certification_efficiency",
            "netBilledWithoutVAT",
            "netCollected",
            "netDue",
            "created_at",
            "updated_at",
        ]

    def get_projectName(self, obj) -> str:
        return obj.project_name

    def get_invoiceType(self, obj) -> str:
        return obj.invoice_type

    def get_grossBilled(self, obj):
        return obj.gross_billed

    def get_grossCertifiedBilled(self, obj):
        return obj.gross_certified_billed

    def get_difference(self, obj) -> Decimal:
        return metrics_from_record(obj)["difference"]

    def get_certification_efficiency(self, obj) -> Decimal:
        return metrics_from_record(obj)["certification_efficiency"]

    def get_netBilledWithoutVAT(self, obj):
        return obj.gross_billed

    def get_netCollected(self, obj):
        return obj.gross_certified_billed

    def get_netDue(self, obj) -> Decimal:
        return self.get_difference(obj)

    def to_internal_value(self, data):
        if hasattr(data, "copy"):
            data = data.copy()
        else:
            data = dict(data)

        if "projectName" in data and "project_name" not in data:
            data["project_name"] = data["projectName"]
        if "invoiceType" in data and "invoice_type" not in data:
            data["invoice_type"] = data["invoiceType"]
        if "grossBilled" in data and "gross_billed" not in data:
            data["gross_billed"] = data["grossBilled"]
        if "grossCertifiedBilled" in data and "gross_certified_billed" not in data:
            data["gross_certified_billed"] = data["grossCertifiedBilled"]
        if "netBilledWithoutVAT" in data and "gross_billed" not in data:
            data["gross_billed"] = data["netBilledWithoutVAT"]
        if "netCollected" in data and "gross_certified_billed" not in data:
            data["gross_certified_billed"] = data["netCollected"]

        if "invoice_type" in data:
            data["invoice_type"] = _normalize_invoice_type(str(data["invoice_type"]))

        return super().to_internal_value(data)

    def validate_project_name(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("project_name cannot be blank.")
        return value

    def validate_invoice_type(self, value: str) -> str:
        value = _normalize_invoice_type(value)
        allowed = {
            InvoicingInformation.InvoiceType.SCL,
            InvoicingInformation.InvoiceType.CONTRACTOR,
        }
        if value not in allowed:
            raise serializers.ValidationError(
                "invoice_type must be SCL or CONTRACTOR."
            )
        return value

    def _validate_non_negative(self, value: Decimal, field_name: str) -> Decimal:
        if value is not None and value < 0:
            raise serializers.ValidationError(
                f"{field_name} must be >= 0. Negative values are not allowed."
            )
        return value if value is not None else _ZERO

    def validate_gross_billed(self, value: Decimal) -> Decimal:
        return self._validate_non_negative(value, "gross_billed")

    def validate_gross_certified_billed(self, value: Decimal) -> Decimal:
        return self._validate_non_negative(value, "gross_certified_billed")
