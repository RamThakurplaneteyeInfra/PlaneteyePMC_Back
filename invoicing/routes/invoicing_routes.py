"""
Invoicing Information URL routes.

Uses DRF DefaultRouter to auto-generate standard REST endpoints,
plus custom @action routes for filter lookups.

Generated routes:
  POST   /api/invoicing/                                          -> create
  GET    /api/invoicing/                                          -> list
  GET    /api/invoicing/{id}/                                     -> retrieve
  PUT    /api/invoicing/{id}/                                     -> update (full)
  PATCH  /api/invoicing/{id}/                                     -> partial update
  DELETE /api/invoicing/{id}/                                     -> destroy

Custom filter routes (via @action):
  GET    /api/invoicing/project/{projectName}/                    -> all types for project
  GET    /api/invoicing/type/{invoiceType}/                       -> all projects for type
  GET    /api/invoicing/project/{projectName}/type/{invoiceType}/ -> exact lookup
"""

from rest_framework.routers import DefaultRouter

from ..controllers.invoicing_controller import InvoicingInformationViewSet

router = DefaultRouter()
router.register(
    r"invoicing",
    InvoicingInformationViewSet,
    basename="invoicing",
)

# urlpatterns is imported by invoicing/urls.py
urlpatterns = router.urls
