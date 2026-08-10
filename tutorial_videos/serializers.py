"""Serializers for Tutorial Videos — frontend only sends title, description, upload."""

from __future__ import annotations

from rest_framework import serializers

from tutorial_videos.models import TutorialVideo


class TutorialVideoUploadSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255, required=True, allow_blank=False)
    description = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=5000
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

    def validate_title(self, value):
        title = (value or "").strip()
        if not title:
            raise serializers.ValidationError("Title cannot be blank.")
        return title


class TutorialVideoListSerializer(serializers.ModelSerializer):
    class Meta:
        model = TutorialVideo
        fields = [
            "id",
            "title",
            "description",
            "status",
            "created_at",
        ]


class TutorialVideoDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = TutorialVideo
        fields = [
            "id",
            "title",
            "description",
            "status",
            "created_at",
            "updated_at",
            "duration_seconds",
            "file_size",
            "width",
            "height",
        ]


class TutorialVideoCreateResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = TutorialVideo
        fields = ["id", "title", "description", "status"]
