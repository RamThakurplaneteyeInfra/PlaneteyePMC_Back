from rest_framework import serializers

from correspondence.models.attachment import CorrespondenceDocumentAttachment


class CorrespondenceAttachmentUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    document_type = serializers.CharField(
        max_length=120,
        required=False,
        allow_blank=True,
        trim_whitespace=True,
    )
    description = serializers.CharField(required=False, allow_blank=True)


class CorrespondenceAttachmentPatchSerializer(serializers.Serializer):
    document_type = serializers.CharField(
        max_length=120,
        required=False,
        allow_blank=True,
        trim_whitespace=True,
    )
    description = serializers.CharField(required=False, allow_blank=True)
    file = serializers.FileField(required=False)


class CorrespondenceAttachmentSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.SerializerMethodField()
    correspondence_id = serializers.IntegerField(source="correspondence.id", read_only=True)

    class Meta:
        model = CorrespondenceDocumentAttachment
        fields = [
            "id",
            "correspondence_id",
            "file_name",
            "description",
            "document_type",
            "document_version",
            "original_file_size",
            "compressed_file_size",
            "compression_percentage",
            "content_type",
            "uploaded_by",
            "uploaded_by_name",
            "uploaded_at",
            "updated_at",
            "is_active",
        ]
        read_only_fields = fields

    def _display_user(self, user):
        if not user:
            return None
        return user.get_full_name() or user.username

    def get_uploaded_by_name(self, obj):
        return self._display_user(obj.uploaded_by)


class CorrespondenceAttachmentDetailSerializer(CorrespondenceAttachmentSerializer):
    download_url = serializers.SerializerMethodField()
    download_url_expires_in_seconds = serializers.IntegerField(
        source="_download_url_expires_in_seconds",
        read_only=True,
        default=600,
    )

    class Meta(CorrespondenceAttachmentSerializer.Meta):
        fields = CorrespondenceAttachmentSerializer.Meta.fields + [
            "download_url",
            "download_url_expires_in_seconds",
        ]

    def get_download_url(self, obj):
        return getattr(obj, "_download_url", None)
