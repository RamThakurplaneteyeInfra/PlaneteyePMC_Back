"""
Project Dates app URL configuration.

Final URL structure (when mounted at /api/ in backend/urls.py):
  POST   /api/project-dates/
  GET    /api/project-dates/
  GET    /api/project-dates/{id}/
  PUT    /api/project-dates/{id}/
  PATCH  /api/project-dates/{id}/
  DELETE /api/project-dates/{id}/
  GET    /api/project-dates/project/{projectName}/
  GET    /api/project-dates/project/{projectName}/bg-status/
  POST   /api/project-dates/project/{projectName}/bg-status/
  PATCH  /api/project-dates/project/{projectName}/bg-status/
  GET    /api/project-dates/?export=csv
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import ProjectDatesViewSet

router = DefaultRouter()
router.register(r"project-dates", ProjectDatesViewSet, basename="project-dates")

urlpatterns = [
    path("", include(router.urls)),
]
