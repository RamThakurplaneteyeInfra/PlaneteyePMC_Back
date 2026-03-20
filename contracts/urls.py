from rest_framework.routers import DefaultRouter
from django.urls import path, include

from .views import ContractViewSet


router = DefaultRouter()
router.register(r"contracts", ContractViewSet, basename="contracts")

urlpatterns = [
    path("", include(router.urls)),
]

