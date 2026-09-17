from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import MeetingDocumentViewSet

router = DefaultRouter()
router.register(r"meeting-documents", MeetingDocumentViewSet, basename="meeting-documents")

urlpatterns = [
    path("", include(router.urls)),
]
