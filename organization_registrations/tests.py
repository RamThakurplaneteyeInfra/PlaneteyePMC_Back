"""Tests for public organization registration API (onboarding request only)."""

import shutil
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from organization_registrations.models import OrganizationRegistration
from organization_registrations.serializers import OrganizationRegistrationSerializer
from organization_registrations.storage import MAX_LOGO_BYTES

User = get_user_model()

URL = "/api/organization-registrations/"

TINY_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _png(name="logo.png", content=TINY_PNG):
    return SimpleUploadedFile(name, content, content_type="image/png")


def _payload(**overrides):
    data = {
        "legal_name": "Acme Infrastructure Private Limited",
        "display_name": "Acme Infra",
        "office_address": "12 Marine Drive, Mumbai",
        "city": "Mumbai",
        "pin": "400001",
        "phone": "+91 9876543210",
        "official_email": "ops@acme.example",
        "admin_name": "Priya Shah",
        "admin_email": "priya@acme.example",
        "logo": _png(),
    }
    data.update(overrides)
    return data


class OrganizationRegistrationValidationTests(SimpleTestCase):
    """Serializer-level checks that do not need a migrated database."""

    def test_missing_legal_name(self):
        payload = _payload()
        del payload["legal_name"]
        serializer = OrganizationRegistrationSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn("legal_name", serializer.errors)

    def test_invalid_official_email(self):
        serializer = OrganizationRegistrationSerializer(
            data=_payload(official_email="not-an-email")
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("official_email", serializer.errors)
        self.assertIn(
            "Enter a valid official email.",
            [str(msg) for msg in serializer.errors["official_email"]],
        )

    def test_oversized_logo(self):
        huge = _png(content=b"\x89PNG\r\n\x1a\n" + b"\x00" * (MAX_LOGO_BYTES + 10))
        serializer = OrganizationRegistrationSerializer(data=_payload(logo=huge))
        self.assertFalse(serializer.is_valid())
        self.assertIn("logo", serializer.errors)
        self.assertIn(
            "Logo must be 1.5 MB or smaller.",
            [str(msg) for msg in serializer.errors["logo"]],
        )

    def test_wrong_logo_type(self):
        bad = SimpleUploadedFile("logo.gif", b"GIF89a" + b"\x00" * 16, content_type="image/gif")
        serializer = OrganizationRegistrationSerializer(data=_payload(logo=bad))
        self.assertFalse(serializer.is_valid())
        self.assertIn("logo", serializer.errors)


class OrganizationRegistrationAPITest(APITestCase):
    def setUp(self):
        self.media_dir = tempfile.mkdtemp()
        self._media_override = override_settings(MEDIA_ROOT=self.media_dir)
        self._media_override.enable()
        self.user_count_before = User.objects.count()

    def tearDown(self):
        self._media_override.disable()
        shutil.rmtree(self.media_dir, ignore_errors=True)

    def _post(self, **overrides):
        return self.client.post(URL, _payload(**overrides), format="multipart")

    @patch("organization_registrations.views.notify_organization_registration")
    def test_happy_path_creates_pending_request_without_user_or_login(self, mock_notify):
        response = self._post()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertTrue(response.data["success"])
        self.assertIn("No login was created", response.data["message"])

        data = response.data["data"]
        self.assertEqual(data["legal_name"], "Acme Infrastructure Private Limited")
        self.assertEqual(data["display_name"], "Acme Infra")
        self.assertEqual(data["city"], "Mumbai")
        self.assertEqual(data["official_email"], "ops@acme.example")
        self.assertEqual(data["admin_email"], "priya@acme.example")
        self.assertEqual(data["status"], "pending")
        self.assertTrue(data["logo_url"])
        self.assertIsNotNone(data["id"])
        self.assertIsNotNone(data["submitted_at"])
        self.assertNotIn("access", response.data)
        self.assertNotIn("refresh", response.data)
        self.assertNotIn("token", response.data)

        row = OrganizationRegistration.objects.get(pk=data["id"])
        self.assertEqual(row.status, OrganizationRegistration.STATUS_PENDING)
        self.assertTrue(row.logo)
        mock_notify.assert_called_once()
        self.assertEqual(User.objects.count(), self.user_count_before)

    def test_missing_field_returns_400_field_errors(self):
        payload = _payload()
        del payload["legal_name"]
        response = self.client.post(URL, payload, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["message"], "Validation failed")
        self.assertIn("legal_name", response.data["errors"])
        self.assertFalse(OrganizationRegistration.objects.exists())

    def test_invalid_email_returns_400(self):
        response = self._post(official_email="not-an-email")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])
        self.assertIn("official_email", response.data["errors"])
        self.assertIn(
            "Enter a valid official email.",
            [str(msg) for msg in response.data["errors"]["official_email"]],
        )
        self.assertFalse(OrganizationRegistration.objects.exists())

    def test_oversized_logo_returns_400(self):
        huge = _png(content=b"\x89PNG\r\n\x1a\n" + b"\x00" * (MAX_LOGO_BYTES + 10))
        response = self._post(logo=huge)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])
        self.assertIn("logo", response.data["errors"])
        self.assertIn(
            "Logo must be 1.5 MB or smaller.",
            [str(msg) for msg in response.data["errors"]["logo"]],
        )
        self.assertFalse(OrganizationRegistration.objects.exists())

    @patch("services.email_utils.send_html_email", side_effect=RuntimeError("smtp down"))
    def test_email_failure_still_returns_201(self, _mock_send):
        response = self._post()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(OrganizationRegistration.objects.count(), 1)
        self.assertEqual(User.objects.count(), self.user_count_before)
