from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ScopeCategoryViewSet, ScopeSubCategoryViewSet,
    MonthlyScopeWorkViewSet, forward_multiple_scopes
)

router = DefaultRouter()
router.register(r'categories', ScopeCategoryViewSet)
router.register(r'subcategories', ScopeSubCategoryViewSet)
router.register(r'', MonthlyScopeWorkViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path('forward/', forward_multiple_scopes, name='forward-multiple-scopes'),
]