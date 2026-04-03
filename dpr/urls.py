from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import DailyProgressReportViewSet
from .wpr_views import WeeklyProgressReportAPIView

# Create router and register viewsets
router = DefaultRouter()
router.register(r'dpr', DailyProgressReportViewSet, basename='dpr')

urlpatterns = [
    path('wpr/', WeeklyProgressReportAPIView.as_view(), name='weekly-progress-report'),
    path('', include(router.urls)),
]
