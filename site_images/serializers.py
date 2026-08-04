"""
Serializers for Site Progress Images.
"""

from rest_framework import serializers

from .models import SiteProgressImage

MAX_IMAGES_PER_REQUEST = 20
TITLE_MAX_LENGTH = 255


def normalize_title(value) -> str:
    """Coerce optional title to a trimmed string (max 255). Empty if missing."""
    if value is None:
        return ""
    text = str(value).strip()
    if len(text) > TITLE_MAX_LENGTH:
        raise serializers.ValidationError(
            f"Title must be at most {TITLE_MAX_LENGTH} characters."
        )
    return text


class SiteProgressImageSerializer(serializers.ModelSerializer):
    """Read serializer for gallery listings; PATCH may update title only."""

    uploaded_by_username = serializers.SerializerMethodField()
    title = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=TITLE_MAX_LENGTH,
    )

    class Meta:
        model = SiteProgressImage
        fields = [
            "id",
            "project_name",
            "month",
            "year",
            "title",
            "image_url",
            "cloudinary_public_id",
            "storage_backend",
            "uploaded_by",
            "uploaded_by_username",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
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

    def get_uploaded_by_username(self, obj) -> str | None:
        if obj.uploaded_by_id:
            return obj.uploaded_by.username
        return None

    def validate_title(self, value) -> str:
        return normalize_title(value)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Existing rows / null titles serialize as empty string for FE stability
        data["title"] = data.get("title") or ""
        return data


class SiteProgressImageUploadResponseSerializer(serializers.Serializer):
    """Compact upload response item."""

    id = serializers.IntegerField()
    title = serializers.CharField(allow_blank=True)
    image_url = serializers.URLField()
    public_id = serializers.CharField()


class SiteProgressImageUploadSerializer(serializers.Serializer):
    """Validates multipart upload metadata (files validated in the view)."""

    project_name = serializers.CharField(max_length=255, trim_whitespace=True)
    month = serializers.IntegerField(min_value=1, max_value=12)
    year = serializers.IntegerField(min_value=2000, max_value=2100)
    # Optional single title applied to all images when titles[] is absent
    title = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=TITLE_MAX_LENGTH,
    )

    def validate_project_name(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("project_name is required.")
        return value

    def validate_title(self, value) -> str:
        return normalize_title(value)

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
