"""
Correspondence Document Serializer.

Writable: project_name, month, year, correspondence_type, description,
          received_date, delivered_date
Auto: sr_no, deadline_date, delivered_status
"""

from django.db.models import Prefetch
from rest_framework import serializers

from ..models.attachment import CorrespondenceDocumentAttachment
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
        CorrespondenceDocument.TYPE_OTHER_AGENCY,
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
            "correspondence_category",
            "party_type",
            "flow_direction",
            "sender",
            "recipient_type",
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
            "sender",
            "sr_no",
            "deadline_date",
            "delivered_status",
            "delivery_date",
            "delivery_status",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            "flow_direction": {"required": False},
            "recipient_type": {"required": False, "allow_null": True},
        }

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
        if "recipient_type" in data and data["recipient_type"]:
            data["recipient_type"] = _normalize_correspondence_type(
                str(data["recipient_type"])
            )
            if "correspondence_type" not in data or not data.get("correspondence_type"):
                data["correspondence_type"] = data["recipient_type"]
        if "correspondence_category" in data:
            category = str(data["correspondence_category"]).strip().upper()
            if category in (
                CorrespondenceDocument.CATEGORY_DELIVERY,
                CorrespondenceDocument.CATEGORY_RECORD,
            ):
                data["correspondence_category"] = category

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
            CorrespondenceDocument.TYPE_OTHER_AGENCY,
        }
        if value not in allowed:
            raise serializers.ValidationError(
                "correspondence_type must be CLIENT, CONTRACTOR, or OTHER_AGENCY."
            )
        return value

    def validate_correspondence_category(self, value: str) -> str:
        if not value:
            return CorrespondenceDocument.CATEGORY_DELIVERY
        normalized = value.strip().upper()
        allowed = {
            CorrespondenceDocument.CATEGORY_DELIVERY,
            CorrespondenceDocument.CATEGORY_RECORD,
        }
        if normalized not in allowed:
            raise serializers.ValidationError(
                "correspondence_category must be DELIVERY or RECORD."
            )
        return normalized

    def validate(self, attrs):
        flow = attrs.get(
            "flow_direction",
            self.instance.flow_direction if self.instance else CorrespondenceDocument.FLOW_INBOUND,
        )
        recipient = attrs.get(
            "recipient_type",
            self.instance.recipient_type if self.instance else None,
        )

        if (
            flow == CorrespondenceDocument.FLOW_INBOUND
            and recipient
            and not (self.instance and self.instance.flow_direction == CorrespondenceDocument.FLOW_INBOUND)
        ):
            attrs["flow_direction"] = CorrespondenceDocument.FLOW_OUTBOUND_SCL
            flow = CorrespondenceDocument.FLOW_OUTBOUND_SCL

        if flow == CorrespondenceDocument.FLOW_OUTBOUND_SCL:
            if not recipient:
                raise serializers.ValidationError(
                    {
                        "recipient_type": (
                            "recipient_type is required for SCL outbound documents."
                        )
                    }
                )
            attrs["correspondence_type"] = recipient
            attrs["sender"] = CorrespondenceDocument.SENDER_SCL

        category = attrs.get(
            "correspondence_category",
            getattr(self.instance, "correspondence_category", None)
            if self.instance
            else CorrespondenceDocument.CATEGORY_DELIVERY,
        )
        if category == CorrespondenceDocument.CATEGORY_RECORD:
            attrs["delivered_date"] = None

        return self._validate_dates(attrs)

    def _validate_dates(self, attrs):
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
        flow = validated_data.get(
            "flow_direction", CorrespondenceDocument.FLOW_INBOUND
        )
        validated_data["sr_no"] = CorrespondenceDocument.next_sr_no(
            validated_data["project_name"],
            validated_data["month"],
            validated_data["year"],
            validated_data["correspondence_type"],
            flow_direction=flow,
        )
        return CorrespondenceDocument.objects.create(**validated_data)


class CorrespondenceDocumentReadSerializer(CorrespondenceDocumentSerializer):
    attachment_count = serializers.SerializerMethodField()
    latest_attachment = serializers.SerializerMethodField()
    attachments = serializers.SerializerMethodField()

    class Meta(CorrespondenceDocumentSerializer.Meta):
        fields = CorrespondenceDocumentSerializer.Meta.fields + [
            "attachment_count",
            "latest_attachment",
            "attachments",
        ]

    def _active_attachments(self, obj):
        prefetched = getattr(obj, "_prefetched_objects_cache", {})
        if "attachments" in prefetched:
            return [item for item in prefetched["attachments"] if item.is_active]
        return list(
            CorrespondenceDocumentAttachment.objects.filter(
                correspondence=obj,
                is_active=True,
            ).order_by("-uploaded_at", "-document_version")
        )

    def get_attachment_count(self, obj):
        count = getattr(obj, "attachment_count", None)
        if count is not None:
            return count
        return len(self._active_attachments(obj))

    def get_latest_attachment(self, obj):
        attachments = self._active_attachments(obj)
        if not attachments:
            return None
        latest = attachments[0]
        return {
            "id": latest.id,
            "file_name": latest.file_name,
            "document_type": latest.document_type,
            "uploaded_at": latest.uploaded_at,
        }

    def get_attachments(self, obj):
        if not self.context.get("include_attachments"):
            return None
        from services.s3_correspondence_documents import generate_presigned_download_url

        from .attachment_serializer import CorrespondenceAttachmentDetailSerializer

        attachments = self._active_attachments(obj)
        payload = []
        for attachment in attachments:
            attachment._download_url = generate_presigned_download_url(attachment.s3_key)
            attachment._download_url_expires_in_seconds = 600
            payload.append(CorrespondenceAttachmentDetailSerializer(attachment).data)
        return payload


ATTACHMENT_PREFETCH = Prefetch(
    "attachments",
    queryset=CorrespondenceDocumentAttachment.objects.filter(
        is_active=True,
    ).order_by("-uploaded_at", "-document_version"),
)
