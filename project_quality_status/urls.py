"""
Project Quality Status app URL configuration.

All routes are defined in routes/quality_status_routes.py and
included here so backend/urls.py only needs a single include().

Final URL structure (when mounted at /api/ in backend/urls.py):
  POST   /api/project-quality-status/
  GET    /api/project-quality-status/
  GET    /api/project-quality-status/{id}/
  PUT    /api/project-quality-status/{id}/
  PATCH  /api/project-quality-status/{id}/
  DELETE /api/project-quality-status/{id}/
  GET    /api/project-quality-status/project/{projectName}/
"""

from django.urls import include, path

from .routes.quality_status_routes import urlpatterns as pqs_urlpatterns

urlpatterns = [
    path("", include(pqs_urlpatterns)),
]
