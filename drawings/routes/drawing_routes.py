"""
Drawing URL routes.

Uses DRF DefaultRouter to auto-generate standard REST endpoints:

  POST   /api/drawings/                          -> create
  GET    /api/drawings/                          -> list (with optional ?project_name= filter)
  GET    /api/drawings/{id}/                     -> retrieve
  PUT    /api/drawings/{id}/                     -> update (full)
  PATCH  /api/drawings/{id}/                     -> partial_update
  DELETE /api/drawings/{id}/                     -> destroy
  GET    /api/drawings/project/{projectName}/    -> get_by_project_name (custom action)
"""

from rest_framework.routers import DefaultRouter

from ..controllers.drawing_controller import DrawingViewSet

# Register the ViewSet with the router
router = DefaultRouter()
router.register(r"drawings", DrawingViewSet, basename="drawing")

# urlpatterns is imported by drawings/urls.py
urlpatterns = router.urls
