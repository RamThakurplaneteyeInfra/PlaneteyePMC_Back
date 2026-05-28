"""
Invoicing app URL configuration.

All routes are defined in routes/invoicing_routes.py and
included here so backend/urls.py only needs a single include().

Final URL structure (when mounted at /api/ in backend/urls.py):
  POST   /api/invoicing/
  GET    /api/invoicing/
  GET    /api/invoicing/{id}/
  PUT    /api/invoicing/{id}/
  PATCH  /api/invoicing/{id}/
  DELETE /api/invoicing/{id}/
  GET    /api/invoicing/project/{projectName}/
  GET    /api/invoicing/type/{invoiceType}/
  GET    /api/invoicing/project/{projectName}/type/{invoiceType}/
"""

from django.urls import include, path

from .routes.invoicing_routes import urlpatterns as invoicing_urlpatterns

urlpatterns = [
    path("", include(invoicing_urlpatterns)),
]
