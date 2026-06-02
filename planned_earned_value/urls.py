"""
Planned vs Earned Value app URL configuration.

Mounted at /api/ in backend/urls.py.
"""

from django.urls import include, path

from .routes.planned_earned_value_routes import urlpatterns as pev_urlpatterns

urlpatterns = [
    path("", include(pev_urlpatterns)),
]
