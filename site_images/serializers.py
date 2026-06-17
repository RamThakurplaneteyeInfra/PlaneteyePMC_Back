"""
Serializers for Site Progress Images.
"""

from rest_framework import serializers

from .models import SiteProgressImage

MAX_IMAGES_PER_REQUEST = 20


class SiteProgressImageSerializer(serializers.ModelSerializer):
    """Full read serializer for gallery listings."""

    uploaded_by_username = serializers.SerializerMethodField()

    class Meta:
        model = SiteProgressImage
        fields = [
            "id",
            "project_name",
            "month",
            "year",
            "image_url",
            "cloudinary_public_id",
            "storage_backend",
            "uploaded_by",
            "uploaded_by_username",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_uploaded_by_username(self, obj) -> str | None:
        if obj.uploaded_by_id:
            return obj.uploaded_by.username
        return None


class SiteProgressImageUploadResponseSerializer(serializers.Serializer):
    """Compact upload response item."""

    id = serializers.IntegerField()
    image_url = serializers.URLField()
    public_id = serializers.CharField()


class SiteProgressImageUploadSerializer(serializers.Serializer):
    """Validates multipart upload metadata (files validated in the view)."""

    project_name = serializers.CharField(max_length=255, trim_whitespace=True)
    month = serializers.IntegerField(min_value=1, max_value=12)
    year = serializers.IntegerField(min_value=2000, max_value=2100)

    def validate_project_name(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("project_name is required.")
        return value

    @staticmethod
    def validate_files(files: list) -> list:
        if not files:
            raise serializers.ValidationError(
                "At least one image file is required."
            )
        if len(files) > MAX_IMAGES_PER_REQUEST:
            raise serializers.ValidationError(
                f"A maximum of {MAX_IMAGES_PER_REQUEST} images "
                "may be uploaded per request."
            )
        return files
