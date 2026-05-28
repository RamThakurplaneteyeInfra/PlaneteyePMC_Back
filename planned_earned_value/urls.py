"""
Planned vs Earned Value app URL configuration.

All routes are defined in routes/planned_earned_value_routes.py and
included here so backend/urls.py only needs a single include().

Final URL structure (when mounted at /api/ in backend/urls.py):
  POST   /api/planned-earned-value/
  GET    /api/planned-earned-value/
  GET    /api/planned-earned-value/{id}/
  PUT    /api/planned-earned-value/{id}/
  PATCH  /api/planned-earned-value/{id}/
  DELETE /api/planned-earned-value/{id}/
  GET    /api/planned-earned-value/project/{projectName}/
"""

from django.urls import include, path

from .routes.planned_earned_value_routes import urlpatterns as pev_urlpatterns

urlpatterns = [
    path("", include(pev_urlpatterns)),
]
