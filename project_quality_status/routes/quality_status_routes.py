"""
Project Quality Status URL routes.

Uses DRF DefaultRouter to auto-generate standard REST endpoints,
plus a custom @action route for project-name lookup.

Generated routes:
  POST   /api/project-quality-status/                          -> create
  GET    /api/project-quality-status/                          -> list
  GET    /api/project-quality-status/{id}/                     -> retrieve
  PUT    /api/project-quality-status/{id}/                     -> update (full)
  PATCH  /api/project-quality-status/{id}/                     -> partial update
  DELETE /api/project-quality-status/{id}/                     -> destroy

Custom route (via @action):
  GET    /api/project-quality-status/project/{projectName}/    -> get_by_project_name
"""

from rest_framework.routers import DefaultRouter

from ..controllers.quality_status_controller import ProjectQualityStatusViewSet

router = DefaultRouter()
router.register(
    r"project-quality-status",
    ProjectQualityStatusViewSet,
    basename="project-quality-status",
)

# urlpatterns is imported by project_quality_status/urls.py
urlpatterns = router.urls
