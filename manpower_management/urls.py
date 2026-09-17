from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import ManpowerRecordViewSet

router = DefaultRouter()
router.register(r'manpower', ManpowerRecordViewSet, basename='manpower')

urlpatterns = [
    path('', include(router.urls)),
]
