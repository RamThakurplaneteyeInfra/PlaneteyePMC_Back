from django.urls import path

from core.cache_health import CacheHealthAPIView

urlpatterns = [
    path("cache-health/", CacheHealthAPIView.as_view(), name="cache-health"),
]
