from rest_framework import serializers

from .models import MeetingDocument


class MeetingDocumentSerializer(serializers.ModelSerializer):
    project_name = serializers.CharField(source="project.name", read_only=True)
    uploaded_by_name = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    updated_by_name = serializers.SerializerMethodField()

    class Meta:
        model = MeetingDocument
        fields = [
            "id",
            "project",
            "project_name",
            "uploaded_by",
            "uploaded_by_name",
            "meeting_type",
            "title",
            "description",
            "meeting_date",
            "meeting_number",
            "document_version",
            "file_name",
            "original_file_size",
            "compressed_file_size",
            "compression_percentage",
            "content_type",
            "s3_key",
            "s3_url",
            "uploaded_at",
            "updated_at",
            "is_active",
            "created_by",
            "created_by_name",
            "updated_by",
            "updated_by_name",
        ]
        read_only_fields = fields

    def _display_user(self, user):
        if not user:
            return None
        return user.get_full_name() or user.username

    def get_uploaded_by_name(self, obj):
        return self._display_user(obj.uploaded_by)

    def get_created_by_name(self, obj):
        return self._display_user(obj.created_by)

    def get_updated_by_name(self, obj):
        return self._display_user(obj.updated_by)


class MeetingDocumentDetailSerializer(MeetingDocumentSerializer):
    download_url = serializers.SerializerMethodField()
    download_url_expires_in_seconds = serializers.IntegerField(
        source="_download_url_expires_in_seconds",
        read_only=True,
        default=600,
    )

    class Meta(MeetingDocumentSerializer.Meta):
        fields = MeetingDocumentSerializer.Meta.fields + [
            "download_url",
            "download_url_expires_in_seconds",
        ]

    def get_download_url(self, obj):
        return getattr(obj, "_download_url", None)


class MeetingDocumentUploadSerializer(serializers.Serializer):
    project_name = serializers.CharField(max_length=255, trim_whitespace=True)
    meeting_type = serializers.ChoiceField(choices=MeetingDocument.MEETING_TYPE_CHOICES)
    title = serializers.CharField(max_length=255, trim_whitespace=True)
    description = serializers.CharField(required=False, allow_blank=True)
    meeting_date = serializers.DateField()
    meeting_number = serializers.CharField(
        max_length=80,
        required=False,
        allow_blank=True,
        trim_whitespace=True,
    )
    document_version = serializers.IntegerField(required=False, min_value=1)
    file = serializers.FileField()

    def validate_project_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("project_name is required.")
        return value


class MeetingDocumentPatchSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255, required=False, trim_whitespace=True)
    description = serializers.CharField(required=False, allow_blank=True)
    meeting_date = serializers.DateField(required=False)
    meeting_number = serializers.CharField(
        max_length=80,
        required=False,
        allow_blank=True,
        trim_whitespace=True,
    )
    document_version = serializers.IntegerField(required=False, min_value=1)
    file = serializers.FileField(required=False)
