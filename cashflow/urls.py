from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import CashFlowViewSet

router = DefaultRouter()
router.register(r"cashflow", CashFlowViewSet, basename="cashflow")

urlpatterns = [
    path("", include(router.urls)),
]
