from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import ProjectCostPerformanceViewSet

router = DefaultRouter()
router.register(
    r"cost-performance",
    ProjectCostPerformanceViewSet,
    basename="cost-performance",
)

urlpatterns = [
    path("", include(router.urls)),
]
