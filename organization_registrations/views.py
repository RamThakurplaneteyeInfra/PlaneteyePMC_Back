import logging

from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .notifications import notify_organization_registration
from .serializers import OrganizationRegistrationSerializer

logger = logging.getLogger(__name__)

SUCCESS_MESSAGE = (
    "Organization registration submitted. PlanetEye will contact the admin "
    "to complete onboarding. No login was created."
)


class OrganizationRegistrationCreateView(APIView):
    """
    Public POST /api/organization-registrations/

    Saves an onboarding request only. Does not create users, JWTs, or workspaces.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser, FormParser]
    http_method_names = ["post", "options", "head"]

    def _error(self, errors, message="Validation failed"):
        field_errors = {}
        for field, value in dict(errors).items():
            if isinstance(value, (list, tuple)):
                field_errors[field] = [str(item) for item in value]
            else:
                field_errors[field] = [str(value)]
        response = Response(
            {"success": False, "message": message, "errors": field_errors},
            status=status.HTTP_400_BAD_REQUEST,
        )
        response._pmc_preserve_error_envelope = True
        return response

    @swagger_auto_schema(
        operation_summary="Submit organization registration request",
        operation_description=(
            "Public onboarding request. Multipart form with organization details "
            "and a logo. Does not create a user account or login. "
            "No Authorization header. Use POST and OPTIONS."
        ),
        tags=["Organization Registrations"],
        consumes=["multipart/form-data"],
    )
    def post(self, request, *args, **kwargs):
        serializer = OrganizationRegistrationSerializer(
            data=request.data,
            context={"request": request},
        )
        if not serializer.is_valid():
            return self._error(serializer.errors)

        registration = serializer.save()
        try:
            notify_organization_registration(registration)
        except Exception:
            logger.exception(
                "Organization registration email notify failed id=%s",
                registration.pk,
            )

        output = OrganizationRegistrationSerializer(
            registration,
            context={"request": request},
        )
        return Response(
            {
                "success": True,
                "message": SUCCESS_MESSAGE,
                "data": output.data,
            },
            status=status.HTTP_201_CREATED,
        )
