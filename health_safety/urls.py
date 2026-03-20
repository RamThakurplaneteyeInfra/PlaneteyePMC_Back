# Health & Safety URLs
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

# Create router for ViewSet
router = DefaultRouter()
router.register(r'reports', views.HealthSafetyReportViewSet, basename='health-safety-report')

urlpatterns = [
    # Main status calculation endpoint
    path('status/', views.health_safety_status, name='health-safety-status'),
    
    # Example endpoint
    path('example/', views.health_safety_example, name='health-safety-example'),
    
    # Include router URLs
    path('', include(router.urls)),
]
