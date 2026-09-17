"""
JWT auth serializers — token login + user payload.
"""

from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.exceptions import AuthenticationFailed
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


def _normalize_login_payload(data):
    """Accept username, email, user, or login as the credential identifier."""
    if not hasattr(data, "get"):
        return data

    payload = data.copy() if hasattr(data, "copy") else dict(data)
    if (payload.get("username") or "").strip():
        return payload

    for field in ("email", "user", "login"):
        value = (payload.get(field) or "").strip()
        if value:
            payload["username"] = value
            break
    return payload


def resolve_user_for_login(identifier: str):
    """
    Resolve an active user from username or email (case-insensitive).

    Returns the User instance or None.
    """
    login_id = (identifier or "").strip()
    if not login_id:
        return None

    user = User.objects.filter(username__iexact=login_id).first()
    if user is None:
        user = User.objects.filter(email__iexact=login_id).first()
    return user


class AuthUserSerializer(serializers.ModelSerializer):
    """User payload on login and /api/auth/me/."""

    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "email", "full_name"]

    def get_full_name(self, obj) -> str:
        name = obj.get_full_name()
        return name.strip() if name else obj.username


class CustomTokenObtainPairSerializer(serializers.Serializer):
    """Validate username/password and return JWT tokens + user."""

    username = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)
    email = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def to_internal_value(self, data):
        return super().to_internal_value(_normalize_login_payload(data))

    def validate(self, attrs):
        identifier = (attrs.get("username") or attrs.get("email") or "").strip()
        password = attrs.get("password")

        if not identifier or password is None:
            raise AuthenticationFailed("Invalid username/password.", code="authorization")

        user = resolve_user_for_login(identifier)
        if user is None or not user.check_password(password):
            raise AuthenticationFailed(
                "Incorrect username or password.",
                code="authorization",
            )
        if not user.is_active:
            raise AuthenticationFailed(
                "Your account has been disabled. Please contact the administrator.",
                code="authorization",
            )

        refresh = RefreshToken.for_user(user)
        return {
            "refresh": str(refresh),
            "access": str(refresh.access_token),
            "user": AuthUserSerializer(user).data,
        }
