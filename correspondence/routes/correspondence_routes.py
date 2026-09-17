"""
Correspondence document routes.

  POST   /api/correspondence-documents/
  GET    /api/correspondence-documents/
  GET    /api/correspondence-documents/{id}/
  PATCH  /api/correspondence-documents/{id}/
  DELETE /api/correspondence-documents/{id}/
  GET    /api/correspondence-documents/dashboard/?project_name=&month=&year=
"""

from rest_framework.routers import DefaultRouter

from ..controllers.correspondence_controller import CorrespondenceDocumentViewSet
from ..controllers.attachment_controller import CorrespondenceAttachmentViewSet

router = DefaultRouter()
router.register(
    r"correspondence-documents",
    CorrespondenceDocumentViewSet,
    basename="correspondence-documents",
)
router.register(
    r"correspondence-documents/attachments",
    CorrespondenceAttachmentViewSet,
    basename="correspondence-attachments",
)
# Legacy frontend path (same ViewSet as correspondence-documents)
router.register(
    r"correspondence",
    CorrespondenceDocumentViewSet,
    basename="correspondence",
)

urlpatterns = router.urls
