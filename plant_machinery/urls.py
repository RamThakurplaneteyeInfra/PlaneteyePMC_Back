from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    MachineryItemViewSet,
    MachineryMasterViewSet,
    PlantMachineryReportViewSet,
)

router = DefaultRouter()
router.register(r"machinery-master", MachineryMasterViewSet, basename="machinery-master")
router.register(r"plant-machinery", PlantMachineryReportViewSet, basename="plant-machinery")
router.register(r"items", MachineryItemViewSet, basename="items")

urlpatterns = [
    path("", include(router.urls)),
]
