"""
Correspondence Document Serializer.

Writable: project_name, month, year, correspondence_type, description,
          received_date, delivered_date
Auto: sr_no, deadline_date, delivered_status
"""

from rest_framework import serializers

from ..models.correspondence import CorrespondenceDocument

_STRIP_ON_WRITE = {
    "correspondence_received",
    "correspondence_delivered",
    "correspondenceReceived",
    "correspondenceDelivered",
    "received_count",
    "delivered_count",
    "pending_count",
    "received",
    "delivered",
    "pending",
    "delivery_efficiency",
    "deliveryPercentage",
    "pendingCorrespondence",
    "pending_correspondence",
    "deadline_date",
    "delivered_status",
    "delivery_status",
    "sr_no",
}


def _normalize_correspondence_type(value: str) -> str:
    if not value:
        return value
    normalized = value.strip().upper()
    if normalized in (
        CorrespondenceDocument.TYPE_CLIENT,
        CorrespondenceDocument.TYPE_CONTRACTOR,
    ):
        return normalized
    return value.strip()


class CorrespondenceDocumentSerializer(serializers.ModelSerializer):
    projectName = serializers.SerializerMethodField()
    party_type = serializers.SerializerMethodField()
    # Legacy read aliases
    delivery_date = serializers.DateField(source="delivered_date", read_only=True)
    delivery_status = serializers.CharField(source="delivered_status", read_only=True)

    class Meta:
        model = CorrespondenceDocument
        fields = [
            "id",
            "project_name",
            "projectName",
            "month",
            "year",
            "correspondence_type",
            "party_type",
            "sr_no",
            "description",
            "received_date",
            "deadline_date",
            "delivered_date",
            "delivered_status",
            "delivery_date",
            "delivery_status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "projectName",
            "party_type",
            "sr_no",
            "deadline_date",
            "delivered_status",
            "delivery_date",
            "delivery_status",
            "created_at",
            "updated_at",
        ]

    def get_projectName(self, obj) -> str:
        return obj.project_name

    def get_party_type(self, obj) -> str:
        return obj.correspondence_type

    def to_internal_value(self, data):
        if hasattr(data, "copy"):
            data = data.copy()
        else:
            data = dict(data)

        if "projectName" in data and "project_name" not in data:
            data["project_name"] = data["projectName"]
        if "party_type" in data and "correspondence_type" not in data:
            data["correspondence_type"] = data["party_type"]
        if "correspondence_type" in data:
            data["correspondence_type"] = _normalize_correspondence_type(
                str(data["correspondence_type"])
            )

        # Legacy request field names
        if "delivery_date" in data and "delivered_date" not in data:
            data["delivered_date"] = data["delivery_date"]

        for field in _STRIP_ON_WRITE:
            data.pop(field, None)

        return super().to_internal_value(data)

    def validate_project_name(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("project_name cannot be blank.")
        return value

    def validate_month(self, value: int) -> int:
        if not (1 <= value <= 12):
            raise serializers.ValidationError("month must be between 1 and 12.")
        return value

    def validate_year(self, value: int) -> int:
        if not (2000 <= value <= 2100):
            raise serializers.ValidationError("year must be between 2000 and 2100.")
        return value

    def validate_correspondence_type(self, value: str) -> str:
        value = _normalize_correspondence_type(value)
        allowed = {
            CorrespondenceDocument.TYPE_CLIENT,
            CorrespondenceDocument.TYPE_CONTRACTOR,
        }
        if value not in allowed:
            raise serializers.ValidationError(
                "correspondence_type must be CLIENT or CONTRACTOR."
            )
        return value

    def validate(self, attrs):
        instance = self.instance
        received = attrs.get(
            "received_date",
            instance.received_date if instance else None,
        )
        month = attrs.get("month", instance.month if instance else None)
        year = attrs.get("year", instance.year if instance else None)
        delivered = attrs.get(
            "delivered_date",
            instance.delivered_date if instance else None,
        )

        if received and month and year:
            if received.month != month or received.year != year:
                raise serializers.ValidationError(
                    {
                        "received_date": (
                            "received_date must fall within the selected "
                            "month and year."
                        )
                    }
                )

        if received and delivered and delivered < received:
            raise serializers.ValidationError(
                {
                    "delivered_date": (
                        "delivered_date cannot be before received_date."
                    )
                }
            )

        return attrs

    def create(self, validated_data):
        validated_data["sr_no"] = CorrespondenceDocument.next_sr_no(
            validated_data["project_name"],
            validated_data["month"],
            validated_data["year"],
            validated_data["correspondence_type"],
        )
        return CorrespondenceDocument.objects.create(**validated_data)
