from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import TutorialVideoViewSet

router = DefaultRouter()
router.register(r"tutorial-videos", TutorialVideoViewSet, basename="tutorial-videos")

urlpatterns = [
    path("", include(router.urls)),
]
