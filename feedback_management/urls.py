from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import ProjectFeedbackViewSet

router = DefaultRouter()
router.register(r"project-feedback", ProjectFeedbackViewSet, basename="project-feedback")

urlpatterns = [
    path("", include(router.urls)),
]
