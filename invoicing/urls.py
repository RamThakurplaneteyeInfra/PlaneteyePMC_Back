from rest_framework.routers import DefaultRouter
from django.urls import path, include

from .views import InvoicingInformationViewSet


router = DefaultRouter()
router.register(r"invoicing", InvoicingInformationViewSet, basename="invoicing")

urlpatterns = [
    path("", include(router.urls)),
]
