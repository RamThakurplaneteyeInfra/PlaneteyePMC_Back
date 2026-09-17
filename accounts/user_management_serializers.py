"""Serializers for HO / Admin User Management APIs."""

from django.contrib.auth import get_user_model
from rest_framework import serializers

from accounts.models import UserProfile
from accounts.rbac import MANAGEABLE_PROJECT_ROLES
from accounts.user_management_services import get_assigned_projects_for_user
from accounts.utils import get_user_role

User = get_user_model()


class ManagedUserProjectSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    status = serializers.CharField()


class ManagedUserSerializer(serializers.ModelSerializer):
    """List / detail representation (never includes password hash)."""

    full_name = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()
    phone_number = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    assigned_projects = serializers.SerializerMethodField()
    created_date = serializers.DateTimeField(source="date_joined", read_only=True)

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "role",
            "phone_number",
            "status",
            "is_active",
            "assigned_projects",
            "created_date",
            "last_login",
        )
        read_only_fields = fields

    def get_full_name(self, obj):
        name = obj.get_full_name().strip()
        return name or obj.username

    def get_role(self, obj):
        return get_user_role(obj)

    def get_phone_number(self, obj):
        try:
            return obj.profile.phone_number or ""
        except UserProfile.DoesNotExist:
            return ""

    def get_status(self, obj):
        return "active" if obj.is_active else "inactive"

    def get_assigned_projects(self, obj):
        mapping = self.context.get("assigned_projects_by_user")
        if mapping is not None:
            projects = mapping.get(obj.id, [])
        else:
            projects = get_assigned_projects_for_user(obj)
        return ManagedUserProjectSerializer(projects, many=True).data


class ManagedUserCreateSerializer(serializers.Serializer):
    full_name = serializers.CharField(required=False, allow_blank=True, max_length=255)
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField(required=False, allow_blank=True)
    phone_number = serializers.CharField(
        required=False, allow_blank=True, max_length=20
    )
    role = serializers.ChoiceField(choices=[(r, r) for r in sorted(MANAGEABLE_PROJECT_ROLES)])
    project_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
    )
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    confirm_password = serializers.CharField(
        write_only=True, required=False, allow_blank=True, trim_whitespace=False
    )
    is_active = serializers.BooleanField(required=False, default=True)
    # Aliases accepted from frontend variants
    project = serializers.IntegerField(required=False, write_only=True)
    projects = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        write_only=True,
    )
    mobile = serializers.CharField(required=False, allow_blank=True, max_length=20)
    mobile_number = serializers.CharField(
        required=False, allow_blank=True, max_length=20
    )
    status = serializers.ChoiceField(
        choices=["active", "inactive"], required=False, write_only=True
    )

    def to_internal_value(self, data):
        payload = data.copy() if hasattr(data, "copy") else dict(data)
        if not payload.get("project_ids"):
            if payload.get("projects"):
                payload["project_ids"] = payload.get("projects")
            elif payload.get("project"):
                payload["project_ids"] = [payload.get("project")]
        if not payload.get("phone_number"):
            payload["phone_number"] = (
                payload.get("mobile")
                or payload.get("mobile_number")
                or payload.get("phone_number")
                or ""
            )
        if payload.get("status") and "is_active" not in payload:
            payload["is_active"] = str(payload["status"]).lower() == "active"
        return super().to_internal_value(payload)


class ManagedUserUpdateSerializer(serializers.Serializer):
    full_name = serializers.CharField(required=False, allow_blank=True, max_length=255)
    username = serializers.CharField(required=False, max_length=150)
    email = serializers.EmailField(required=False, allow_blank=True)
    phone_number = serializers.CharField(
        required=False, allow_blank=True, max_length=20
    )
    role = serializers.ChoiceField(
        choices=[(r, r) for r in sorted(MANAGEABLE_PROJECT_ROLES)],
        required=False,
    )
    project_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=False,
    )
    is_active = serializers.BooleanField(required=False)
    mobile = serializers.CharField(required=False, allow_blank=True, max_length=20)
    mobile_number = serializers.CharField(
        required=False, allow_blank=True, max_length=20
    )
    status = serializers.ChoiceField(
        choices=["active", "inactive"], required=False, write_only=True
    )
    projects = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        write_only=True,
    )

    def to_internal_value(self, data):
        payload = data.copy() if hasattr(data, "copy") else dict(data)
        if "project_ids" not in payload and payload.get("projects") is not None:
            payload["project_ids"] = payload.get("projects")
        if "phone_number" not in payload:
            if payload.get("mobile") is not None:
                payload["phone_number"] = payload.get("mobile")
            elif payload.get("mobile_number") is not None:
                payload["phone_number"] = payload.get("mobile_number")
        if payload.get("status") is not None and "is_active" not in payload:
            payload["is_active"] = str(payload["status"]).lower() == "active"
        return super().to_internal_value(payload)


class PasswordChangeSerializer(serializers.Serializer):
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    confirm_password = serializers.CharField(
        write_only=True, required=False, allow_blank=True, trim_whitespace=False
    )
    new_password = serializers.CharField(
        write_only=True, required=False, trim_whitespace=False
    )

    def to_internal_value(self, data):
        payload = data.copy() if hasattr(data, "copy") else dict(data)
        if not payload.get("password") and payload.get("new_password"):
            payload["password"] = payload.get("new_password")
        return super().to_internal_value(payload)


class AssignProjectsSerializer(serializers.Serializer):
    project_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
    )
    projects = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        write_only=True,
    )

    def to_internal_value(self, data):
        payload = data.copy() if hasattr(data, "copy") else dict(data)
        if not payload.get("project_ids") and payload.get("projects"):
            payload["project_ids"] = payload.get("projects")
        return super().to_internal_value(payload)


class StatusUpdateSerializer(serializers.Serializer):
    is_active = serializers.BooleanField(required=False)
    status = serializers.ChoiceField(
        choices=["active", "inactive"], required=False, write_only=True
    )

    def validate(self, attrs):
        if attrs.get("is_active") is None and attrs.get("status") is None:
            raise serializers.ValidationError(
                {"status": "Please provide status or is_active."}
            )
        if attrs.get("is_active") is None:
            attrs["is_active"] = attrs["status"] == "active"
        return attrs
