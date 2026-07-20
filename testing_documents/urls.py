from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import TestingDocumentViewSet

router = DefaultRouter()
router.register(r"testing-documents", TestingDocumentViewSet, basename="testing-documents")

urlpatterns = [
    path("", include(router.urls)),
]
