from django.urls import path

from .views import OrganizationRegistrationCreateView

urlpatterns = [
    path(
        "organization-registrations/",
        OrganizationRegistrationCreateView.as_view(),
        name="organization-registration-create",
    ),
]
