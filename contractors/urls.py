from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .controllers.contractor_controller import ContractorViewSet

router = DefaultRouter()
router.register(r"", ContractorViewSet, basename="contractors")

urlpatterns = [
    path("", include(router.urls)),
]
