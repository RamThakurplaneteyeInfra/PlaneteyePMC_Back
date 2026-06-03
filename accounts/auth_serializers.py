"""
JWT auth serializers — token login + user payload.
"""

from django.contrib.auth import authenticate, get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.exceptions import AuthenticationFailed
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


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

    username = serializers.CharField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate(self, attrs):
        user = authenticate(
            request=self.context.get("request"),
            username=attrs.get("username"),
            password=attrs.get("password"),
        )
        if user is None or not user.is_active:
            raise AuthenticationFailed("Invalid username/password.", code="authorization")

        refresh = RefreshToken.for_user(user)
        return {
            "refresh": str(refresh),
            "access": str(refresh.access_token),
            "user": AuthUserSerializer(user).data,
        }
