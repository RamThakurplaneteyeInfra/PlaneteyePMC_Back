# Health & Safety URLs
#
# Mounted at /api/health-safety/ in backend/urls.py:
#
#   POST   /api/health-safety/                                          — create monthly record
#   GET    /api/health-safety/                                          — list (filter: project_name, year, month)
#   GET    /api/health-safety/{id}/                                       — retrieve by ID
#   PUT    /api/health-safety/{id}/                                       — update
#   DELETE /api/health-safety/{id}/                                       — delete
#   GET    /api/health-safety/project/{projectName}/month/{m}/year/{y}/ — single month
#   GET    /api/health-safety/project/{projectName}/year/{year}/summary/ — yearly SUM aggregation
#   GET    /api/health-safety/project/{projectName}/dashboard/          — current month + YTD
#
#   POST   /api/health-safety/status/                                   — analytics calculator
#   GET    /api/health-safety/example/                                  — example payload
#   CRUD   /api/health-safety/reports/                                  — legacy date-based reports

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

# ─── Monthly Health & Safety records (primary API) ───────────────────────────
records_router = DefaultRouter()
records_router.register(
    r"", views.HealthSafetyRecordViewSet, basename="health-safety-record"
)

# ─── Legacy analytics router ───────────────────────────────────────────────────
analytics_router = DefaultRouter()
analytics_router.register(
    r"reports", views.HealthSafetyReportViewSet, basename="health-safety-report"
)

urlpatterns = [
    path("status/", views.health_safety_status, name="health-safety-status"),
    path("example/", views.health_safety_example, name="health-safety-example"),
    path("reports/", include(analytics_router.urls)),
    path("", include(records_router.urls)),
]

# ─── Legacy cumulative HSE records (mounted at /api/ via hse_urls) ─────────────
hse_router = DefaultRouter()
hse_router.register(r"hse", views.HSERecordViewSet, basename="hse-record")
hse_urlpatterns = hse_router.urls
