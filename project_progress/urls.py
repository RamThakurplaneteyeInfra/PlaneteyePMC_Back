from rest_framework.routers import DefaultRouter
from django.urls import path, include

from .views import ProjectProgressStatusViewSet


router = DefaultRouter()
router.register(r"project-progress", ProjectProgressStatusViewSet, basename="project-progress")

urlpatterns = [
    path("", include(router.urls)),
]
