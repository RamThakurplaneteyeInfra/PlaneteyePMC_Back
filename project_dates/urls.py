"""
Project Dates app URL configuration.

Final URL structure (when mounted at /api/ in backend/urls.py):
  POST   /api/project-dates/
  GET    /api/project-dates/
  ...
  GET/POST/PATCH/DELETE /api/project-eot/
  GET    /api/project-eot/project/{projectName}/
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .eot_views import ProjectEOTViewSet
from .views import ProjectDatesViewSet

router = DefaultRouter()
router.register(r"project-dates", ProjectDatesViewSet, basename="project-dates")
router.register(r"project-eot", ProjectEOTViewSet, basename="project-eot")

urlpatterns = [
    path("", include(router.urls)),
]
