"""
Monthly Construction Progress URL routes.

Uses DRF DefaultRouter to auto-generate standard REST endpoints,
plus custom @action routes for project-name and month lookups.

Generated routes:
  POST   /api/construction-progress/                               -> create
  GET    /api/construction-progress/                               -> list
  GET    /api/construction-progress/{id}/                          -> retrieve
  PUT    /api/construction-progress/{id}/                          -> update (full)
  PATCH  /api/construction-progress/{id}/                          -> partial update
  DELETE /api/construction-progress/{id}/                          -> destroy

Custom routes (via @action):
  GET    /api/construction-progress/project/{projectName}/         -> get_by_project_name
  GET    /api/construction-progress/month/{progressMonth}/         -> get_by_month
"""

from rest_framework.routers import DefaultRouter

from ..controllers.construction_progress_controller import ConstructionProgressViewSet

router = DefaultRouter()
router.register(
    r"construction-progress",
    ConstructionProgressViewSet,
    basename="construction-progress",
)

urlpatterns = router.urls
