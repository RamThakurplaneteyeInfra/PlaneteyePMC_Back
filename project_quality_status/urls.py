"""
Project Quality Status app URL configuration.

Mounted at /api/ in backend/urls.py.

  /api/project-quality/              — primary routes
  /api/project-quality-status/       — legacy alias (same ViewSet)
"""

from django.urls import include, path

from .routes.quality_status_routes import urlpatterns as pqs_urlpatterns

urlpatterns = [
    path("", include(pqs_urlpatterns)),
]
