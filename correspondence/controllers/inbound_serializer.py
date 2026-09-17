"""Serializer for inbound (Client / Contractor) correspondence summary save/load."""

from rest_framework import serializers

from ..models.inbound_summary import InboundCorrespondenceSummary
from .correspondence_metrics import VIEW_CUMULATIVE, VIEW_MONTHLY, normalize_view


def _parse_count(value) -> int:
    if value in (None, ""):
        return 0
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        raise serializers.ValidationError("Count must be a non-negative integer.")


def extract_inbound_counts(data: dict) -> dict:
    """Read client/contractor received/delivered counts from flat or nested payloads."""
    client_nested = data.get("client") if isinstance(data.get("client"), dict) else {}
    contractor_nested = data.get("contractor") if isinstance(data.get("contractor"), dict) else {}

    counts = {}
    for category, nested in (
        ("client", client_nested),
        ("contractor", contractor_nested),
    ):
        for metric in ("received", "delivered"):
            flat_key = f"{category}_{metric}"
            value = data.get(flat_key)
            if value is None and nested:
                value = nested.get(metric)
            counts[flat_key] = _parse_count(value)
    return counts


class InboundCorrespondenceSerializer(serializers.Serializer):
    project_name = serializers.CharField()
    month = serializers.IntegerField(min_value=1, max_value=12)
    year = serializers.IntegerField(min_value=2000, max_value=2100)
    view = serializers.CharField(required=False, default=VIEW_MONTHLY)

    client_received = serializers.IntegerField(
        min_value=0, required=False, default=0, allow_null=True
    )
    client_delivered = serializers.IntegerField(
        min_value=0, required=False, default=0, allow_null=True
    )
    contractor_received = serializers.IntegerField(
        min_value=0, required=False, default=0, allow_null=True
    )
    contractor_delivered = serializers.IntegerField(
        min_value=0, required=False, default=0, allow_null=True
    )

    def validate_project_name(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("project_name cannot be blank.")
        return value

    def validate_view(self, value):
        return normalize_view(value)

    def validate(self, attrs):
        data = self.initial_data if hasattr(self, "initial_data") else attrs
        if isinstance(data, dict):
            attrs.update(extract_inbound_counts(data))
        return attrs

    def to_representation(self, instance):
        if isinstance(instance, InboundCorrespondenceSummary):
            from .correspondence_metrics import inbound_summary_to_api

            document_qs = self.context.get("document_qs")
            return inbound_summary_to_api(instance, document_qs)
        return super().to_representation(instance)
