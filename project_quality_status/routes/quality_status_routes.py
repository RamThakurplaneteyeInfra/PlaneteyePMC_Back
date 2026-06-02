"""
Project Quality Status URL routes.

  POST   /api/project-quality/
  GET    /api/project-quality/
  GET    /api/project-quality/{id}/
  PUT    /api/project-quality/{id}/
  PATCH  /api/project-quality/{id}/
  DELETE /api/project-quality/{id}/
  GET    /api/project-quality/project/{projectName}/
  GET    /api/project-quality/project/{projectName}/month/{month}/year/{year}/
  GET    /api/project-quality/project/{projectName}/year/{year}/summary/

Legacy alias (backward compatible):
  /api/project-quality-status/  → same ViewSet
"""

from rest_framework.routers import DefaultRouter

from ..controllers.quality_status_controller import ProjectQualityStatusViewSet

router = DefaultRouter()
router.register(
    r"project-quality",
    ProjectQualityStatusViewSet,
    basename="project-quality",
)

legacy_router = DefaultRouter()
legacy_router.register(
    r"project-quality-status",
    ProjectQualityStatusViewSet,
    basename="project-quality-status",
)

urlpatterns = router.urls + legacy_router.urls
