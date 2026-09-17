"""
Correspondence app URL configuration.

  POST   /api/correspondence-documents/
  GET    /api/correspondence-documents/
  GET    /api/correspondence-documents/{id}/
  PATCH  /api/correspondence-documents/{id}/
  DELETE /api/correspondence-documents/{id}/
  GET    /api/correspondence-documents/dashboard/?project_name=&month=&year=

Legacy aliases (same handlers):
  /api/correspondence/  →  /api/correspondence-documents/
"""

from django.urls import include, path

from .routes.correspondence_routes import urlpatterns as correspondence_urlpatterns

urlpatterns = [
    path("", include(correspondence_urlpatterns)),
]
