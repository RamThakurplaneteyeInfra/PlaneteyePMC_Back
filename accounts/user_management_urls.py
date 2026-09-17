from django.urls import include, path
from rest_framework.routers import DefaultRouter

from accounts.user_management_views import ManagedUserViewSet

router = DefaultRouter()
router.register(r"users", ManagedUserViewSet, basename="managed-users")

urlpatterns = [
    path("", include(router.urls)),
]
