from rest_framework.routers import DefaultRouter
from django.urls import path, include

from .views import ContractPerformanceViewSet


router = DefaultRouter()
router.register(r"contract-performance", ContractPerformanceViewSet, basename="contract-performance")

urlpatterns = [
    path("", include(router.urls)),
]
