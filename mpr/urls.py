from django.urls import path

from .views import (
    MPRDetailAPIView,
    MPRExcelDownloadAPIView,
    MPRGenerateAPIView,
    MPRHistoryAPIView,
    MPRPdfDownloadAPIView,
    MPRPreviewAPIView,
    MPRRegenerateAPIView,
)

urlpatterns = [
    path(
        "mpr/projects/<int:project_id>/preview/",
        MPRPreviewAPIView.as_view(),
        name="mpr-preview",
    ),
    path(
        "mpr/projects/<int:project_id>/generate/",
        MPRGenerateAPIView.as_view(),
        name="mpr-generate",
    ),
    path(
        "mpr/projects/<int:project_id>/",
        MPRHistoryAPIView.as_view(),
        name="mpr-history",
    ),
    path(
        "mpr/<int:mpr_id>/",
        MPRDetailAPIView.as_view(),
        name="mpr-detail",
    ),
    path(
        "mpr/<int:mpr_id>/regenerate/",
        MPRRegenerateAPIView.as_view(),
        name="mpr-regenerate",
    ),
    path(
        "mpr/<int:mpr_id>/pdf/",
        MPRPdfDownloadAPIView.as_view(),
        name="mpr-pdf",
    ),
    path(
        "mpr/<int:mpr_id>/excel/",
        MPRExcelDownloadAPIView.as_view(),
        name="mpr-excel",
    ),
]
