import logging

from django.db import DatabaseError, OperationalError, ProgrammingError
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .notifications import notify_organization_registration
from .serializers import OrganizationRegistrationSerializer
from .storage import LOGO_STORAGE_UNAVAILABLE, LogoStorageError

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

    def _error(self, errors, message="Validation failed", http_status=status.HTTP_400_BAD_REQUEST):
        field_errors = {}
        for field, value in dict(errors).items():
            if isinstance(value, (list, tuple)):
                field_errors[field] = [str(item) for item in value]
            else:
                field_errors[field] = [str(value)]
        response = Response(
            {"success": False, "message": message, "errors": field_errors},
            status=http_status,
        )
        response._pmc_preserve_error_envelope = True
        return response

    def _service_unavailable(self, message, *, logo_message=None):
        errors = {}
        if logo_message:
            errors["logo"] = [logo_message]
        response = Response(
            {
                "success": False,
                "message": message,
                "errors": errors,
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
        response._pmc_preserve_error_envelope = True
        return response

    @swagger_auto_schema(
        operation_summary="Submit organization registration request",
        operation_description=(
            "Public onboarding request. Multipart form with organization details "
            "and an optional logo. Does not create a user account or login. "
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
            errors = serializer.errors
            # Storage misconfiguration is reported on logo — return 503, not 500.
            logo_errs = errors.get("logo") or []
            logo_text = " ".join(str(e) for e in logo_errs)
            if LOGO_STORAGE_UNAVAILABLE in logo_text or "Logo storage is unavailable" in logo_text:
                return self._error(
                    errors,
                    message="Organization logo storage is not configured on the server.",
                    http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
            return self._error(errors)

        try:
            registration = serializer.save()
        except LogoStorageError as exc:
            logger.warning(
                "Organization registration logo storage unavailable: %s",
                exc.message,
            )
            return self._service_unavailable(
                "Organization logo storage is not configured on the server.",
                logo_message=exc.message,
            )
        except OSError:
            logger.exception(
                "Organization registration failed writing logo (read-only media?)"
            )
            return self._service_unavailable(
                "Organization logo storage is not configured on the server.",
                logo_message=LOGO_STORAGE_UNAVAILABLE,
            )
        except (ProgrammingError, OperationalError) as exc:
            # Missing migration / table or DB connectivity on hosted env.
            logger.exception(
                "Organization registration DB error (migrate / DATABASE_URL?): %s",
                exc,
            )
            return self._service_unavailable(
                "Registration service is temporarily unavailable. "
                "Ensure organization_registrations migrations are applied "
                "and DATABASE_URL is configured."
            )
        except DatabaseError:
            logger.exception("Organization registration database error")
            return self._service_unavailable(
                "Registration service is temporarily unavailable. Please try again later."
            )

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
