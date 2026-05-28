"""
Planned vs Earned Value URL routes.

Uses DRF DefaultRouter to auto-generate standard REST endpoints:

  POST   /api/planned-earned-value/                          -> create
  GET    /api/planned-earned-value/                          -> list
  GET    /api/planned-earned-value/{id}/                     -> retrieve
  PUT    /api/planned-earned-value/{id}/                     -> update (full)
  PATCH  /api/planned-earned-value/{id}/                     -> partial update
  DELETE /api/planned-earned-value/{id}/                     -> destroy
  GET    /api/planned-earned-value/project/{projectName}/    -> get_by_project_name
"""

from rest_framework.routers import DefaultRouter

from ..controllers.planned_earned_value_controller import PlannedEarnedValueViewSet

# Register the ViewSet — the router generates all standard URL patterns
router = DefaultRouter()
router.register(
    r"planned-earned-value",
    PlannedEarnedValueViewSet,
    basename="planned-earned-value",
)

# urlpatterns is imported by planned_earned_value/urls.py
urlpatterns = router.urls
