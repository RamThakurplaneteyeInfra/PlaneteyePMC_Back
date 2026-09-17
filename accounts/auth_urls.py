from django.urls import path

from .auth_views import (
    CustomTokenObtainPairView,
    LogoutView,
    MeView,
    TokenRefreshViewAllowAny,
)

urlpatterns = [
    path("login/", CustomTokenObtainPairView.as_view(), name="auth-login"),
    path("refresh/", TokenRefreshViewAllowAny.as_view(), name="auth-refresh"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    path("me/", MeView.as_view(), name="auth-me"),
]
