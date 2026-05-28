"""
Correspondence URL routes.

Uses DRF DefaultRouter to auto-generate standard REST endpoints:

  POST   /api/correspondence/                          -> create
  GET    /api/correspondence/                          -> list
  GET    /api/correspondence/{id}/                     -> retrieve
  PUT    /api/correspondence/{id}/                     -> update (full)
  PATCH  /api/correspondence/{id}/                     -> partial update
  DELETE /api/correspondence/{id}/                     -> destroy
  GET    /api/correspondence/project/{projectName}/    -> get_by_project_name
"""

from rest_framework.routers import DefaultRouter

from ..controllers.correspondence_controller import CorrespondenceViewSet

# Register the ViewSet — the router generates all standard URL patterns
router = DefaultRouter()
router.register(r"correspondence", CorrespondenceViewSet, basename="correspondence")

# urlpatterns is imported by correspondence/urls.py
urlpatterns = router.urls
