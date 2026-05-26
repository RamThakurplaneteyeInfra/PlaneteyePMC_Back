from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ProjectViewSet, SiteViewSet, ProjectLogViewSet

router = DefaultRouter()
router.register(r'projects', ProjectViewSet)
router.register(r'sites', SiteViewSet)
router.register(r'project-logs', ProjectLogViewSet, basename='project-logs')

urlpatterns = [
    path('', include(router.urls)),
]
