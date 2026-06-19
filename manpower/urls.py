from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import ProjectManpowerViewSet

router = DefaultRouter()
router.register(r"manpower-mh", ProjectManpowerViewSet, basename="manpower-mh")

urlpatterns = [
    path("", include(router.urls)),
]
