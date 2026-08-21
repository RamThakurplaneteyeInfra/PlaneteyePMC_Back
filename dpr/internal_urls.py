from django.urls import path

from dpr.internal_views import DprExecutiveDigestTriggerView

urlpatterns = [
    path(
        "executive-digest/",
        DprExecutiveDigestTriggerView.as_view(),
        name="internal-dpr-executive-digest",
    ),
]
