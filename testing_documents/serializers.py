from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from accounts.utils import get_user_role
from projects.models import Project
from services.s3_testing_documents import validate_upload_file

from .models import TestingDocument


class ProjectMiniSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class UploadedBySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    role = serializers.CharField(allow_null=True)


class TestingDocumentSerializer(serializers.ModelSerializer):
    project = serializers.SerializerMethodField()
    uploaded_by = serializers.SerializerMethodField()

    class Meta:
        model = TestingDocument
        fields = [
            "id",
            "project",
            "title",
            "remarks",
            "document_type",
            "file_name",
            "file_url",
            "file_size",
            "mime_type",
            "test_date",
            "month",
            "year",
            "uploaded_by",
            "created_at",
            "updated_at",
            "is_active",
        ]
        read_only_fields = fields

    def get_project(self, obj):
        return {"id": obj.project_id, "name": obj.project.name}

    def get_uploaded_by(self, obj):
        user = obj.uploaded_by
        if not user:
            return None
        return {
            "id": user.id,
            "username": user.username,
            "role": get_user_role(user),
        }


class TestingDocumentUploadSerializer(serializers.Serializer):
    project = serializers.PrimaryKeyRelatedField(queryset=Project.objects.all())
    title = serializers.CharField(max_length=255)
    remarks = serializers.CharField(required=False, allow_blank=True, default="")
    test_date = serializers.DateField()
    file = serializers.FileField()

    def validate_title(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("title is required.")
        return value

    def validate_file(self, value):
        if value is None:
            raise serializers.ValidationError("file is required.")
        try:
            validate_upload_file(value)
        except DjangoValidationError as exc:
            messages = getattr(exc, "messages", None) or [str(exc)]
            raise serializers.ValidationError(messages[0])
        return value


class TestingDocumentUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255, required=False)
    remarks = serializers.CharField(required=False, allow_blank=True)
    test_date = serializers.DateField(required=False)
    file = serializers.FileField(required=False)
    is_active = serializers.BooleanField(required=False)

    def validate_title(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("title cannot be blank.")
        return value

    def validate_file(self, value):
        if value is None:
            return value
        try:
            validate_upload_file(value)
        except DjangoValidationError as exc:
            messages = getattr(exc, "messages", None) or [str(exc)]
            raise serializers.ValidationError(messages[0])
        return value
