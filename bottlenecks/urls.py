from rest_framework.routers import DefaultRouter

from .views import BottleneckViewSet

router = DefaultRouter()
router.register(r"bottlenecks", BottleneckViewSet, basename="bottleneck")

urlpatterns = router.urls
