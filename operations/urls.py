from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import TaskViewSet, DailyProgressReportViewSet

router = DefaultRouter()
router.register(r'tasks', TaskViewSet)
router.register(r'reports', DailyProgressReportViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
