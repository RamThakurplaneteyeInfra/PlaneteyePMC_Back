"""
Drawings app URL configuration.

Mounted at /api/ in backend/urls.py.
"""

from django.urls import include, path

from .routes.drawing_routes import urlpatterns as drawing_urlpatterns

urlpatterns = [
    path("", include(drawing_urlpatterns)),
]
