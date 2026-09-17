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

from django.urls import path
from rest_framework.routers import DefaultRouter

from ..controllers.frequency_chart_controller import (
    FrequencyChartRegisterViewSet,
    FrequencyChartViewSet,
)
from ..controllers.quality_status_controller import ProjectQualityStatusViewSet

router = DefaultRouter()
router.register(
    r"project-quality",
    ProjectQualityStatusViewSet,
    basename="project-quality",
)
router.register(
    r"frequency-chart",
    FrequencyChartViewSet,
    basename="frequency-chart",
)

legacy_router = DefaultRouter()
legacy_router.register(
    r"project-quality-status",
    ProjectQualityStatusViewSet,
    basename="project-quality-status",
)

frequency_register_list = FrequencyChartRegisterViewSet.as_view(
    {"get": "list", "post": "create"}
)
frequency_register_detail = FrequencyChartRegisterViewSet.as_view(
    {
        "get": "retrieve",
        "put": "update",
        "patch": "partial_update",
        "delete": "destroy",
    }
)

urlpatterns = [
    path(
        "frequency-chart/register/",
        frequency_register_list,
        name="frequency-chart-register-list",
    ),
    path(
        "frequency-chart/register/<int:pk>/",
        frequency_register_detail,
        name="frequency-chart-register-detail",
    ),
] + router.urls + legacy_router.urls
