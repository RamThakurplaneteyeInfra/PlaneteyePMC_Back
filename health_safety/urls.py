# Health & Safety URLs
#
# This file is included TWICE in backend/urls.py under different prefixes:
#
#   path('api/health-safety/', include('health_safety.urls'))
#       → /api/health-safety/status/
#       → /api/health-safety/example/
#       → /api/health-safety/reports/
#
#   path('api/', include('health_safety.hse_urls'))
#       → /api/hse/
#       → /api/hse/{id}/
#       → /api/hse/project/{projectName}/

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

# ─── Existing analytics router ───────────────────────────────────────────────
analytics_router = DefaultRouter()
analytics_router.register(
    r"reports", views.HealthSafetyReportViewSet, basename="health-safety-report"
)

# ─── New HSE record CRUD router ──────────────────────────────────────────────
# Generates:
#   POST   /api/hse/
#   GET    /api/hse/
#   GET    /api/hse/{id}/
#   PUT    /api/hse/{id}/
#   PATCH  /api/hse/{id}/
#   DELETE /api/hse/{id}/
#   GET    /api/hse/project/{projectName}/
hse_router = DefaultRouter()
hse_router.register(r"hse", views.HSERecordViewSet, basename="hse-record")

# ─── Analytics URL patterns (mounted at /api/health-safety/) ─────────────────
urlpatterns = [
    # POST /api/health-safety/status/
    path("status/", views.health_safety_status, name="health-safety-status"),
    # GET  /api/health-safety/example/
    path("example/", views.health_safety_example, name="health-safety-example"),
    # CRUD /api/health-safety/reports/
    path("", include(analytics_router.urls)),
]

# ─── HSE record URL patterns (mounted at /api/) ───────────────────────────────
# Imported by backend/urls.py as: path('api/', include('health_safety.hse_urls'))
hse_urlpatterns = hse_router.urls
