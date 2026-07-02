"""Serializer for SCL Delivered Correspondence summary save/load."""

from rest_framework import serializers

from ..models.scl_delivered_summary import SCLDeliveredCorrespondenceSummary
from .correspondence_metrics import VIEW_CUMULATIVE, VIEW_MONTHLY, normalize_view


def _parse_count(value) -> int:
    if value in (None, ""):
        return 0
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        raise serializers.ValidationError("Count must be a non-negative integer.")


def _nested_value(nested: dict, category: str, metric: str):
    value = nested.get(category)
    if isinstance(value, dict):
        return value.get(metric)
    if metric == "delivered":
        return value
    return None


def extract_scl_counts(data: dict) -> dict:
    """Read SCL received/delivered counts from flat, nested, or legacy payloads."""
    nested = data.get("scl_delivered_correspondence") or {}

    counts = {}
    for category in ("client", "contractor", "other_agency"):
        received_key = f"{category}_received"
        delivered_key = f"{category}_delivered"
        legacy_delivered = data.get(category)

        received = data.get(received_key, _nested_value(nested, category, "received"))
        delivered = data.get(
            delivered_key,
            _nested_value(nested, category, "delivered"),
        )
        if delivered is None:
            delivered = legacy_delivered

        counts[received_key] = _parse_count(received)
        counts[delivered_key] = _parse_count(delivered)
    return counts


class SCLDeliveredCorrespondenceSerializer(serializers.Serializer):
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
    other_agency_received = serializers.IntegerField(
        min_value=0, required=False, default=0, allow_null=True
    )
    other_agency_delivered = serializers.IntegerField(
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
            attrs.update(extract_scl_counts(data))
        return attrs

    def to_representation(self, instance):
        if isinstance(instance, SCLDeliveredCorrespondenceSummary):
            from .correspondence_metrics import merge_scl_record_from_documents

            document_qs = self.context.get("document_qs")
            scl_payload = instance.to_api_dict()
            if document_qs is not None:
                scl_payload = merge_scl_record_from_documents(scl_payload, document_qs)
            return {
                "id": instance.id,
                "project_name": instance.project_name,
                "month": instance.month,
                "year": instance.year,
                "view": instance.view,
                "scl_delivered_correspondence": scl_payload,
            }
        return super().to_representation(instance)
