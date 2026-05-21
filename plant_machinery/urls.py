from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import PlantMachineryReportViewSet, MachineryItemViewSet

router = DefaultRouter()
router.register(r'plant-machinery', PlantMachineryReportViewSet, basename='plant-machinery')
router.register(r'items', MachineryItemViewSet, basename='items')

urlpatterns = [
    path('', include(router.urls)),
]
