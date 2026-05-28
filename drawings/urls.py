"""
Drawings app URL configuration.

All drawing routes are defined in routes/drawing_routes.py and
included here so backend/urls.py only needs a single include().

Final URL structure (when mounted at /api/ in backend/urls.py):
  POST   /api/drawings/
  GET    /api/drawings/
  GET    /api/drawings/{id}/
  PUT    /api/drawings/{id}/
  PATCH  /api/drawings/{id}/
  DELETE /api/drawings/{id}/
  GET    /api/drawings/project/{projectName}/
"""

from django.urls import include, path

from .routes.drawing_routes import urlpatterns as drawing_urlpatterns

urlpatterns = [
    path("", include(drawing_urlpatterns)),
]
