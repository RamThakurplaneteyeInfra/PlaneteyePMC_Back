from rest_framework.routers import DefaultRouter

from .alerts_views import AlertViewSet

router = DefaultRouter()
router.register(r"", AlertViewSet, basename="alert")

urlpatterns = router.urls
