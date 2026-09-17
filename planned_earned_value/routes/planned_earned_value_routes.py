"""
Planned vs Actual URL routes.

Primary:
  /api/planned-vs-actual/

Legacy alias (same ViewSet):
  /api/planned-earned-value/
"""

from rest_framework.routers import DefaultRouter

from ..controllers.planned_earned_value_controller import PlannedEarnedValueViewSet

router = DefaultRouter()
router.register(
    r"planned-vs-actual",
    PlannedEarnedValueViewSet,
    basename="planned-vs-actual",
)
router.register(
    r"planned-earned-value",
    PlannedEarnedValueViewSet,
    basename="planned-earned-value",
)

urlpatterns = router.urls
