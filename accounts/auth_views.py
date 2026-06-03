"""
JWT authentication endpoints.

POST /api/token/              — login (SimpleJWT standard, used by frontend)
POST /api/token/refresh/      — refresh access token
POST /api/auth/login/         — login alias (same response as /api/token/)
POST /api/auth/refresh/       — refresh alias
POST /api/auth/logout/        — blacklist refresh token
GET  /api/auth/me/            — current user (simple profile)
GET  /api/accounts/me/        — current user (full profile with roles)
"""

from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .auth_serializers import AuthUserSerializer, CustomTokenObtainPairSerializer


class CustomTokenObtainPairView(TokenObtainPairView):
    """Login — validates auth_user credentials and returns access + refresh + user."""

    permission_classes = [AllowAny]
    authentication_classes = []
    serializer_class = CustomTokenObtainPairSerializer


class TokenRefreshViewAllowAny(TokenRefreshView):
    permission_classes = [AllowAny]
    authentication_classes = []


class LogoutView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            return Response(
                {"detail": "Refresh token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            RefreshToken(refresh_token).blacklist()
        except TokenError:
            return Response(
                {"detail": "Invalid or expired refresh token."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"detail": "Successfully logged out."})


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(AuthUserSerializer(request.user).data)
