from django.urls import path

from core.background_tasks_health import BackgroundTasksHealthAPIView
from core.cache_health import CacheHealthAPIView

urlpatterns = [
    path("cache-health/", CacheHealthAPIView.as_view(), name="cache-health"),
    path(
        "background-tasks/",
        BackgroundTasksHealthAPIView.as_view(),
        name="background-tasks-health",
    ),
]
