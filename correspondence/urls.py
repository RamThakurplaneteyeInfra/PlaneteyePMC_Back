"""
Correspondence app URL configuration.

All routes are defined in routes/correspondence_routes.py and included here
so backend/urls.py only needs a single include().

Final URL structure (when mounted at /api/ in backend/urls.py):
  POST   /api/correspondence/
  GET    /api/correspondence/
  GET    /api/correspondence/{id}/
  PUT    /api/correspondence/{id}/
  PATCH  /api/correspondence/{id}/
  DELETE /api/correspondence/{id}/
  GET    /api/correspondence/project/{projectName}/
"""

from django.urls import include, path

from .routes.correspondence_routes import urlpatterns as correspondence_urlpatterns

urlpatterns = [
    path("", include(correspondence_urlpatterns)),
]
