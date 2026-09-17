"""
Contract Performance app URL configuration.

All routes are defined in routes/contract_performance_routes.py and
included here so backend/urls.py only needs a single include().

Final URL structure (when mounted at /api/ in backend/urls.py):
  POST   /api/contract-performance/
  GET    /api/contract-performance/
  GET    /api/contract-performance/{id}/
  PUT    /api/contract-performance/{id}/
  PATCH  /api/contract-performance/{id}/
  DELETE /api/contract-performance/{id}/
  GET    /api/contract-performance/project/{projectName}/
"""

from django.urls import include, path

from .routes.contract_performance_routes import urlpatterns as cp_urlpatterns

urlpatterns = [
    path("", include(cp_urlpatterns)),
]
