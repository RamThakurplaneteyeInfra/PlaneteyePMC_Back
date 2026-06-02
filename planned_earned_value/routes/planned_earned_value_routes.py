"""
Planned vs Earned Value URL routes.

  POST   /api/planned-earned-value/
  GET    /api/planned-earned-value/
  GET    /api/planned-earned-value/{id}/
  PUT    /api/planned-earned-value/{id}/
  PATCH  /api/planned-earned-value/{id}/
  DELETE /api/planned-earned-value/{id}/
  GET    /api/planned-earned-value/project/{projectName}/
  GET    /api/planned-earned-value/project/{projectName}/month/{month}/year/{year}/
  GET    /api/planned-earned-value/project/{projectName}/year/{year}/summary/
"""

from rest_framework.routers import DefaultRouter

from ..controllers.planned_earned_value_controller import PlannedEarnedValueViewSet

router = DefaultRouter()
router.register(
    r"planned-earned-value",
    PlannedEarnedValueViewSet,
    basename="planned-earned-value",
)

urlpatterns = router.urls
