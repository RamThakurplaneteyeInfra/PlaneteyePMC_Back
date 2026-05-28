"""
Construction Progress app URL configuration.

All routes are defined in routes/construction_progress_routes.py and
included here so backend/urls.py only needs a single include().

Final URL structure (when mounted at /api/ in backend/urls.py):
  POST   /api/construction-progress/
  GET    /api/construction-progress/
  GET    /api/construction-progress/{id}/
  PUT    /api/construction-progress/{id}/
  PATCH  /api/construction-progress/{id}/
  DELETE /api/construction-progress/{id}/
  GET    /api/construction-progress/project/{projectName}/
  GET    /api/construction-progress/month/{progressMonth}/
"""

from django.urls import include, path

from .routes.construction_progress_routes import urlpatterns as cp_urlpatterns

urlpatterns = [
    path("", include(cp_urlpatterns)),
]
