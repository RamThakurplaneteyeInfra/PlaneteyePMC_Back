from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import BudgetCostPerformanceViewSet

router = DefaultRouter()
router.register(
    r"budget-performance",
    BudgetCostPerformanceViewSet,
    basename="budget-performance",
)

urlpatterns = [
    path("", include(router.urls)),
]
