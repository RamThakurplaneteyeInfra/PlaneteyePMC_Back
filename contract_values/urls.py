"""
Contract Values app URL configuration.

All routes are defined in routes/contract_value_routes.py and
included here so backend/urls.py only needs a single include().

Final URL structure (when mounted at /api/ in backend/urls.py):
  POST   /api/contract-values/
  GET    /api/contract-values/
  GET    /api/contract-values/{id}/
  PUT    /api/contract-values/{id}/
  PATCH  /api/contract-values/{id}/
  DELETE /api/contract-values/{id}/
  GET    /api/contract-values/project/{projectName}/
  GET    /api/contract-values/type/{contractType}/
  GET    /api/contract-values/project/{projectName}/type/{contractType}/
"""

from django.urls import include, path

from .routes.contract_value_routes import urlpatterns as cv_urlpatterns

urlpatterns = [
    path("", include(cv_urlpatterns)),
]
