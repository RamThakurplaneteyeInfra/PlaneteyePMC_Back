"""Tests for centralized friendly API error handling."""

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import SimpleTestCase
from rest_framework import status
from rest_framework.exceptions import (
    AuthenticationFailed,
    NotAuthenticated,
    NotFound,
    PermissionDenied,
    Throttled,
    ValidationError,
)
from rest_framework.test import APIRequestFactory, APITestCase
from rest_framework.views import APIView

from core.api_errors import (
    build_error_payload,
    flatten_errors,
    friendly_field_message,
    integrity_error_message,
)
from core.exception_handlers import pmc_exception_handler

User = get_user_model()


class FriendlyMessageUnitTests(SimpleTestCase):
    def test_required_field_message(self):
        self.assertEqual(
            friendly_field_message("notes", "This field is required.", "required"),
            "This field is required to continue.",
        )
        self.assertEqual(
            friendly_field_message("title", "This field is required.", "required"),
            "Please enter a title.",
        )

    def test_date_required(self):
        self.assertEqual(
            friendly_field_message("date", "This field is required.", "required"),
            "Please select a date.",
        )

    def test_project_does_not_exist(self):
        self.assertEqual(
            friendly_field_message(
                "project",
                'Invalid pk "99" - object does not exist.',
                "does_not_exist",
            ),
            "Selected project does not exist.",
        )

    def test_duplicate_pattern(self):
        self.assertEqual(
            friendly_field_message(
                "project_name",
                "contract value with this project name already exists.",
            ),
            "A record with the same details already exists.",
        )

    def test_flatten_serializer_errors(self):
        detail = {
            "project": ["This field is required."],
            "date": ["Date has wrong format. Use one of these formats instead: YYYY-MM-DD."],
        }
        items = flatten_errors(detail)
        fields = {i["field"]: i["message"] for i in items}
        self.assertEqual(fields["project"], "Project is required.")
        self.assertEqual(fields["date"], "Please enter the date in YYYY-MM-DD format.")

    def test_build_error_payload_multiple(self):
        payload = build_error_payload(
            "Validation failed",
            {
                "project": ["This field is required."],
                "contractor": ["This field is required."],
            },
        )
        self.assertFalse(payload["success"])
        self.assertEqual(payload["message"], "Please correct the highlighted fields.")
        self.assertEqual(len(payload["errors"]), 2)

    def test_integrity_unique(self):
        self.assertEqual(
            integrity_error_message(IntegrityError("duplicate key unique constraint")),
            "A record with the same details already exists.",
        )

    def test_integrity_not_null_hyphen(self):
        """Postgres reports 'not-null' (hyphen), not 'not null' (space)."""
        self.assertEqual(
            integrity_error_message(
                IntegrityError(
                    'null value in column "billing_status" of relation '
                    '"projects_project" violates not-null constraint'
                )
            ),
            "Please complete all required fields before submitting.",
        )


class ExceptionHandlerTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()

    def _context(self):
        request = self.factory.get("/api/example/")
        return {"request": request, "view": APIView()}

    def test_validation_error_shape(self):
        exc = ValidationError({"date": ["This field is required."]})
        response = pmc_exception_handler(exc, self._context())
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["errors"][0]["field"], "date")
        self.assertEqual(response.data["errors"][0]["message"], "Please select a date.")

    def test_not_found(self):
        response = pmc_exception_handler(NotFound(), self._context())
        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.data["message"],
            "The requested record could not be found.",
        )

    def test_permission_denied(self):
        response = pmc_exception_handler(PermissionDenied(), self._context())
        self.assertEqual(response.status_code, 403)
        self.assertIn("permission", response.data["message"].lower())

    def test_unauthenticated(self):
        response = pmc_exception_handler(NotAuthenticated(), self._context())
        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.data["success"])

    def test_auth_failed_login(self):
        response = pmc_exception_handler(
            AuthenticationFailed("Incorrect username or password."),
            self._context(),
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data["message"], "Incorrect username or password.")

    def test_throttled(self):
        response = pmc_exception_handler(Throttled(wait=5), self._context())
        self.assertEqual(response.status_code, 429)
        self.assertFalse(response.data["success"])
        self.assertIn("Rate limit", response.data["message"])

    def test_integrity_error(self):
        response = pmc_exception_handler(
            IntegrityError("UNIQUE constraint failed"),
            self._context(),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("already exists", response.data["message"].lower())

    def test_unhandled_hides_traceback(self):
        response = pmc_exception_handler(RuntimeError("secret boom"), self._context())
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("secret boom", str(response.data))
        self.assertEqual(
            response.data["message"],
            "An unexpected error occurred. Please try again later.",
        )


class LoginFriendlyErrorsAPITest(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="err_user", password="Project@123")

    def test_successful_login_unchanged(self):
        response = self.client.post(
            "/api/token/",
            {"username": "err_user", "password": "Project@123"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        # Success envelope must not be forced to success:false
        self.assertNotEqual(response.data.get("success"), False)

    def test_wrong_password(self):
        response = self.client.post(
            "/api/token/",
            {"username": "err_user", "password": "wrong"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertNotIn("access", response.data)
        self.assertFalse(response.data.get("success", True))
        self.assertEqual(response.data.get("message"), "Incorrect username or password.")

    def test_disabled_account(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        response = self.client.post(
            "/api/token/",
            {"username": "err_user", "password": "Project@123"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertNotIn("access", response.data)
        self.assertIn("disabled", (response.data.get("message") or "").lower())
