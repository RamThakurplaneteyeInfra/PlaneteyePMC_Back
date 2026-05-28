"""
Monthly Project Equipment URL routes.

Uses DRF DefaultRouter to auto-generate standard REST endpoints,
plus custom @action routes for project-name and month lookups.

Generated routes:
  POST   /api/project-equipment/                               -> create
  GET    /api/project-equipment/                               -> list
  GET    /api/project-equipment/{id}/                          -> retrieve
  PUT    /api/project-equipment/{id}/                          -> update (full)
  PATCH  /api/project-equipment/{id}/                          -> partial update
  DELETE /api/project-equipment/{id}/                          -> destroy

Custom routes (via @action):
  GET    /api/project-equipment/project/{projectName}/         -> get_by_project_name
  GET    /api/project-equipment/month/{equipmentMonth}/        -> get_by_month
"""

from rest_framework.routers import DefaultRouter

from ..controllers.project_equipment_controller import ProjectEquipmentViewSet

router = DefaultRouter()
router.register(
    r"project-equipment",
    ProjectEquipmentViewSet,
    basename="project-equipment",
)

urlpatterns = router.urls
