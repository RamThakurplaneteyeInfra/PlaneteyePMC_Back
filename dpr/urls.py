from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import DailyProgressReportViewSet

# Create router and register viewsets
router = DefaultRouter()
router.register(r'dpr', DailyProgressReportViewSet, basename='dpr')

urlpatterns = [
    path('', include(router.urls)),
]
