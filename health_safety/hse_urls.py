"""
HSE Record URL configuration.

Mounted at /api/ in backend/urls.py:
    path('api/', include('health_safety.hse_urls'))

Resulting endpoints:
    POST   /api/hse/
    GET    /api/hse/
    GET    /api/hse/{id}/
    PUT    /api/hse/{id}/
    PATCH  /api/hse/{id}/
    DELETE /api/hse/{id}/
    GET    /api/hse/project/{projectName}/
"""

from django.urls import include, path

from .urls import hse_router

urlpatterns = [
    path("", include(hse_router.urls)),
]
