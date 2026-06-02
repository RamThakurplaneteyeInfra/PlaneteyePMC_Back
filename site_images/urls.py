"""
Site Images URL configuration.

Mounted at /api/ in backend/urls.py → /api/site-images/
"""

from rest_framework.routers import DefaultRouter

from .views import SiteProgressImageViewSet

router = DefaultRouter()
router.register(r"site-images", SiteProgressImageViewSet, basename="site-images")

urlpatterns = router.urls
