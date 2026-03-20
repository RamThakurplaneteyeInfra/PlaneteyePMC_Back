from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import ProjectEquipmentViewSet

router = DefaultRouter()
router.register(r"equipment", ProjectEquipmentViewSet, basename="equipment")

urlpatterns = [
    path("", include(router.urls)),
]
