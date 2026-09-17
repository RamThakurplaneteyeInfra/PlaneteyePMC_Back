"""
Drawing URL routes.

Single source of truth: DrawingRegisterItem.

  POST   /api/drawings/register/
  GET    /api/drawings/register/
  PATCH  /api/drawings/register/{id}/
  DELETE /api/drawings/register/{id}/

  DELETE /api/drawings/files/{file_id}/

  GET    /api/drawings/project/{projectName}/summary/?month={m}&year={y}[&view=cumulative]
"""

from django.urls import path

from ..controllers.drawing_controller import DrawingViewSet
from ..controllers.drawing_file_controller import DrawingFileViewSet
from ..controllers.drawing_register_controller import DrawingRegisterViewSet

# DrawingViewSet exposes project_summary as a regular view method (no router needed).
drawing_summary = DrawingViewSet.as_view({"get": "project_summary"})

drawing_register_list = DrawingRegisterViewSet.as_view({"get": "list", "post": "create"})
drawing_register_detail = DrawingRegisterViewSet.as_view(
    {
        "get": "retrieve",
        "patch": "partial_update",
        "delete": "destroy",
    }
)
drawing_file_detail = DrawingFileViewSet.as_view({"delete": "destroy"})

urlpatterns = [
    # Register CRUD
    path("drawings/register/", drawing_register_list, name="drawing-register-list"),
    path(
        "drawings/register/<int:pk>/",
        drawing_register_detail,
        name="drawing-register-detail",
    ),
    path(
        "drawings/files/<int:pk>/",
        drawing_file_detail,
        name="drawing-file-detail",
    ),
    # KPI summary — computed from register records
    path(
        "drawings/project/<str:projectName>/summary/",
        drawing_summary,
        name="drawing-project-summary",
    ),
]
