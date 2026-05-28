"""
Contract Value URL routes.

Uses DRF DefaultRouter to auto-generate standard REST endpoints,
plus custom @action routes for filter lookups.

Generated routes:
  POST   /api/contract-values/                                         -> create
  GET    /api/contract-values/                                         -> list
  GET    /api/contract-values/{id}/                                    -> retrieve
  PUT    /api/contract-values/{id}/                                    -> update (full)
  PATCH  /api/contract-values/{id}/                                    -> partial update
  DELETE /api/contract-values/{id}/                                    -> destroy

Custom filter routes (via @action):
  GET    /api/contract-values/project/{projectName}/                   -> all types for project
  GET    /api/contract-values/type/{contractType}/                     -> all projects for type
  GET    /api/contract-values/project/{projectName}/type/{contractType}/ -> exact lookup
"""

from rest_framework.routers import DefaultRouter

from ..controllers.contract_value_controller import ContractValueViewSet

router = DefaultRouter()
router.register(
    r"contract-values",
    ContractValueViewSet,
    basename="contract-value",
)

# urlpatterns is imported by contract_values/urls.py
urlpatterns = router.urls
