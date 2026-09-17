"""
Project Equipment app URL configuration.

All routes are defined in routes/project_equipment_routes.py and
included here so backend/urls.py only needs a single include().

Final URL structure (when mounted at /api/ in backend/urls.py):
  POST   /api/project-equipment/
  GET    /api/project-equipment/
  GET    /api/project-equipment/{id}/
  PUT    /api/project-equipment/{id}/
  PATCH  /api/project-equipment/{id}/
  DELETE /api/project-equipment/{id}/
  GET    /api/project-equipment/project/{projectName}/
  GET    /api/project-equipment/month/{equipmentMonth}/
"""

from django.urls import include, path

from .routes.project_equipment_routes import urlpatterns as pe_urlpatterns

urlpatterns = [
    path("", include(pe_urlpatterns)),
]
