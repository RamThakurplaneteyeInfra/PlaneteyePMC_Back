"""
Contract Performance URL routes.

Uses DRF DefaultRouter to auto-generate standard REST endpoints,
plus a custom @action route for project-name lookup.

Generated routes:
  POST   /api/contract-performance/                          -> create
  GET    /api/contract-performance/                          -> list
  GET    /api/contract-performance/{id}/                     -> retrieve
  PUT    /api/contract-performance/{id}/                     -> update (full)
  PATCH  /api/contract-performance/{id}/                     -> partial update
  DELETE /api/contract-performance/{id}/                     -> destroy

Custom route (via @action):
  GET    /api/contract-performance/project/{projectName}/    -> get_by_project_name
"""

from rest_framework.routers import DefaultRouter

from ..controllers.contract_performance_controller import ContractPerformanceViewSet

router = DefaultRouter()
router.register(
    r"contract-performance",
    ContractPerformanceViewSet,
    basename="contract-performance",
)

# urlpatterns is imported by contract_performance/urls.py
urlpatterns = router.urls
