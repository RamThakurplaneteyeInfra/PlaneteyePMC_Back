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


def extract_scl_counts(data: dict) -> tuple[int, int, int]:
    """Read client / contractor / other_agency from flat or nested payload."""
    nested = data.get("scl_delivered_correspondence") or {}

    client = (
        data.get("client")
        if data.get("client") is not None
        else data.get("client_delivered", nested.get("client"))
    )
    contractor = (
        data.get("contractor")
        if data.get("contractor") is not None
        else data.get("contractor_delivered", nested.get("contractor"))
    )
    other_agency = (
        data.get("other_agency")
        if data.get("other_agency") is not None
        else data.get("other_agency_delivered", nested.get("other_agency"))
    )

    return _parse_count(client), _parse_count(contractor), _parse_count(other_agency)


class SCLDeliveredCorrespondenceSerializer(serializers.Serializer):
    project_name = serializers.CharField()
    month = serializers.IntegerField(min_value=1, max_value=12)
    year = serializers.IntegerField(min_value=2000, max_value=2100)
    view = serializers.CharField(required=False, default=VIEW_MONTHLY)
    client = serializers.IntegerField(min_value=0, required=False, default=0)
    contractor = serializers.IntegerField(min_value=0, required=False, default=0)
    other_agency = serializers.IntegerField(min_value=0, required=False, default=0)

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
            client, contractor, other_agency = extract_scl_counts(data)
            attrs["client"] = client
            attrs["contractor"] = contractor
            attrs["other_agency"] = other_agency
        return attrs

    def to_representation(self, instance):
        if isinstance(instance, SCLDeliveredCorrespondenceSummary):
            return {
                "id": instance.id,
                "project_name": instance.project_name,
                "month": instance.month,
                "year": instance.year,
                "view": instance.view,
                "scl_delivered_correspondence": instance.to_api_dict(),
            }
        return super().to_representation(instance)
