"""Serializers for Tutorial Videos — title, description, section, upload."""

from __future__ import annotations

from rest_framework import serializers

from tutorial_videos.models import TutorialVideo
from tutorial_videos.sections import (
    TUTORIAL_SECTION_CHOICES,
    section_display_name,
    validate_section_or_error,
)


class TutorialSectionField(serializers.ChoiceField):
    """Normalize and validate sidebar section keys."""

    default_error_messages = {
        "invalid_choice": "Invalid tutorial section.",
        "required": "This field is required.",
        "null": "This field is required.",
    }

    def to_internal_value(self, data):
        try:
            return validate_section_or_error(data if data is not None else "")
        except ValueError as exc:
            msg = str(exc)
            if "required" in msg.lower():
                self.fail("required")
            self.fail("invalid_choice")


class TutorialVideoUploadSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255, required=True, allow_blank=False)
    description = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=5000
    )
    section = TutorialSectionField(
        choices=[c[0] for c in TUTORIAL_SECTION_CHOICES],
        required=True,
    )
    upload = serializers.FileField(required=True, allow_empty_file=False)

    def validate_title(self, value):
        title = (value or "").strip()
        if not title:
            raise serializers.ValidationError("This field is required.")
        return title


class TutorialVideoPatchSerializer(serializers.Serializer):
    title = serializers.CharField(
        max_length=255, required=False, allow_blank=False
    )
    description = serializers.CharField(
        required=False, allow_blank=True, max_length=5000
    )
    section = TutorialSectionField(
        choices=[c[0] for c in TUTORIAL_SECTION_CHOICES],
        required=False,
    )

    def validate_title(self, value):
        title = (value or "").strip()
        if not title:
            raise serializers.ValidationError("Title cannot be blank.")
        return title


class TutorialVideoListSerializer(serializers.ModelSerializer):
    section_name = serializers.SerializerMethodField()

    class Meta:
        model = TutorialVideo
        fields = [
            "id",
            "title",
            "description",
            "section",
            "section_name",
            "status",
            "created_at",
        ]

    def get_section_name(self, obj) -> str:
        return section_display_name(obj.section)


class TutorialVideoDetailSerializer(serializers.ModelSerializer):
    section_name = serializers.SerializerMethodField()

    class Meta:
        model = TutorialVideo
        fields = [
            "id",
            "title",
            "description",
            "section",
            "section_name",
            "status",
            "created_at",
            "updated_at",
            "duration_seconds",
            "file_size",
            "width",
            "height",
            "processing_error",
        ]

    def get_section_name(self, obj) -> str:
        return section_display_name(obj.section)


class TutorialVideoCreateResponseSerializer(serializers.ModelSerializer):
    section_name = serializers.SerializerMethodField()

    class Meta:
        model = TutorialVideo
        fields = [
            "id",
            "title",
            "description",
            "section",
            "section_name",
            "status",
        ]

    def get_section_name(self, obj) -> str:
        return section_display_name(obj.section)
