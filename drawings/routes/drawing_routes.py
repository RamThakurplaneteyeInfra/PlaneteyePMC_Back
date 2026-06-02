"""
Drawing Summary URL routes.

  POST   /api/drawings/
  GET    /api/drawings/
  GET    /api/drawings/{id}/
  PUT    /api/drawings/{id}/
  PATCH  /api/drawings/{id}/
  DELETE /api/drawings/{id}/
  GET    /api/drawings/project/{projectName}/
  GET    /api/drawings/project/{projectName}/month/{month}/year/{year}/
  GET    /api/drawings/project/{projectName}/summary/
  GET    /api/drawings/project/{projectName}/year/{year}/summary/
  GET    /api/drawings/project/{projectName}/dashboard/
"""

from rest_framework.routers import DefaultRouter

from ..controllers.drawing_controller import DrawingViewSet

router = DefaultRouter()
router.register(r"drawings", DrawingViewSet, basename="drawing")

urlpatterns = router.urls
