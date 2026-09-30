"""Tests for public organization registration API (onboarding request only)."""

import shutil
import tempfile
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.mail.backends.base import BaseEmailBackend
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from organization_registrations.models import OrganizationRegistration
from organization_registrations.notifications import attempt_organization_registration_notification
from organization_registrations.serializers import OrganizationRegistrationSerializer
from organization_registrations.storage import LOGO_STORAGE_UNAVAILABLE, MAX_LOGO_BYTES

User = get_user_model()

URL = "/api/organization-registrations/"

TINY_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


class FailingEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        raise RuntimeError("SMTP provider rejected the message")


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

    def test_logo_is_optional(self):
        payload = _payload()
        del payload["logo"]
        serializer = OrganizationRegistrationSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)


class OrganizationRegistrationAPITest(APITestCase):
    def setUp(self):
        self.media_dir = tempfile.mkdtemp()
        # Force local FileField path: empty AWS so tests do not hit real S3.
        self._media_override = override_settings(
            MEDIA_ROOT=self.media_dir,
            AWS_ACCESS_KEY_ID="",
            AWS_SECRET_ACCESS_KEY="",
            AWS_STORAGE_BUCKET_NAME="",
        )
        self._media_override.enable()
        self.user_count_before = User.objects.count()

    def tearDown(self):
        self._media_override.disable()
        shutil.rmtree(self.media_dir, ignore_errors=True)

    def _post(self, **overrides):
        return self.client.post(URL, _payload(**overrides), format="multipart")

    @override_settings(
        EMAIL_TRANSPORT="smtp",
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        BREVO_API_KEY="",
        ORG_REGISTRATION_NOTIFY_EMAIL="planetedevm@gmail.com",
    )
    def test_happy_path_creates_request_and_sends_email_without_user_or_login(self):
        response = self._post(notify_email="attacker@example.com")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertTrue(response.data["success"])
        self.assertTrue(response.data["registration_saved"])
        self.assertEqual(response.data["notification_status"], "sent")
        self.assertIn("No user account or login was created", response.data["message"])

        data = response.data["data"]
        self.assertEqual(data["legal_name"], "Acme Infrastructure Private Limited")
        self.assertEqual(data["display_name"], "Acme Infra")
        self.assertEqual(data["city"], "Mumbai")
        self.assertEqual(data["official_email"], "ops@acme.example")
        self.assertEqual(data["admin_email"], "priya@acme.example")
        self.assertEqual(data["status"], "pending")
        self.assertEqual(data["notification_status"], "sent")
        self.assertTrue(data["logo_url"])
        self.assertIsNotNone(data["id"])
        self.assertIsNotNone(data["submitted_at"])
        self.assertNotIn("access", response.data)
        self.assertNotIn("refresh", response.data)
        self.assertNotIn("token", response.data)

        row = OrganizationRegistration.objects.get(pk=data["id"])
        self.assertEqual(row.status, OrganizationRegistration.STATUS_PENDING)
        self.assertEqual(row.notification_status, OrganizationRegistration.NOTIFICATION_SENT)
        self.assertTrue(row.logo)
        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[0]
        self.assertEqual(sent_email.to, ["planetedevm@gmail.com"])
        self.assertIn("Acme Infra", sent_email.subject)
        body = sent_email.alternatives[0][0]
        self.assertIn("Acme Infrastructure Private Limited", body)
        self.assertIn("Priya Shah", body)
        self.assertIn("priya@acme.example", body)
        self.assertIn("+91 9876543210", body)
        self.assertIn(f"ORG-{row.pk}", body)
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

    def test_invalid_logo_type_returns_400(self):
        bad = SimpleUploadedFile("logo.gif", b"GIF89a" + b"\x00" * 16, content_type="image/gif")
        response = self._post(logo=bad)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])
        self.assertIn("logo", response.data["errors"])
        self.assertFalse(OrganizationRegistration.objects.exists())

    @override_settings(
        EMAIL_TRANSPORT="smtp",
        EMAIL_BACKEND="organization_registrations.tests.FailingEmailBackend",
        ORG_REGISTRATION_NOTIFY_EMAIL="planetedevm@gmail.com",
    )
    def test_email_failure_keeps_registration_and_reports_retryable_status(self):
        response = self._post(notify_email="attacker@example.com")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertTrue(response.data["registration_saved"])
        self.assertEqual(response.data["notification_status"], "failed")
        self.assertIn("could not be sent", response.data["notification_message"])
        self.assertNotIn("attacker@example.com", response.data["notification_message"])
        self.assertEqual(OrganizationRegistration.objects.count(), 1)
        row = OrganizationRegistration.objects.get()
        self.assertEqual(row.notification_status, OrganizationRegistration.NOTIFICATION_FAILED)
        self.assertEqual(User.objects.count(), self.user_count_before)

        with override_settings(
            EMAIL_TRANSPORT="smtp",
            EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
            BREVO_API_KEY="",
        ):
            self.assertTrue(attempt_organization_registration_notification(row))

        row.refresh_from_db()
        self.assertEqual(row.notification_status, OrganizationRegistration.NOTIFICATION_SENT)
        self.assertEqual(OrganizationRegistration.objects.count(), 1)

    @patch("organization_registrations.views.attempt_organization_registration_notification")
    @patch("organization_registrations.storage.is_s3_configured", return_value=True)
    @patch("organization_registrations.storage.is_boto3_available", return_value=True)
    @patch("organization_registrations.storage.get_s3_client")
    def test_s3_path_skips_local_media_and_returns_201(
        self, mock_get_client, _boto, _cfg, mock_notify
    ):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        with override_settings(
            AWS_ACCESS_KEY_ID="x",
            AWS_SECRET_ACCESS_KEY="y",
            AWS_STORAGE_BUCKET_NAME="pmcproject",
            AWS_S3_REGION_NAME="ap-south-1",
        ):
            response = self._post()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        mock_client.upload_fileobj.assert_called_once()
        row = OrganizationRegistration.objects.get()
        self.assertTrue(row.logo_s3_key)
        self.assertTrue(row.logo_s3_url)
        self.assertIn(row.logo_s3_url, response.data["data"]["logo_url"])
        # S3-primary path does not require a local FileField file.
        self.assertFalse(bool(row.logo))
        mock_notify.assert_called_once()

    @patch("organization_registrations.views.attempt_organization_registration_notification")
    def test_registration_without_logo_returns_201(self, mock_notify):
        payload = _payload()
        del payload["logo"]
        response = self.client.post(URL, payload, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertTrue(response.data["success"])
        row = OrganizationRegistration.objects.get()
        self.assertFalse(bool(row.logo))
        self.assertEqual(row.logo_s3_key, "")
        self.assertEqual(row.logo_s3_url, "")
        self.assertEqual(response.data["data"]["logo_url"], "")
        mock_notify.assert_called_once()

    @patch("organization_registrations.storage.media_filesystem_writable", return_value=False)
    @patch("organization_registrations.storage.is_s3_configured", return_value=False)
    @patch("organization_registrations.storage.is_boto3_available", return_value=True)
    def test_serverless_without_s3_returns_503_not_500(self, _boto, _cfg, _writable):
        response = self._post()
        self.assertEqual(
            response.status_code,
            status.HTTP_503_SERVICE_UNAVAILABLE,
            response.data,
        )
        self.assertFalse(response.data["success"])
        self.assertIn("logo", response.data["errors"])
        self.assertIn(
            LOGO_STORAGE_UNAVAILABLE,
            " ".join(str(m) for m in response.data["errors"]["logo"]),
        )
        self.assertFalse(OrganizationRegistration.objects.exists())

    @patch("organization_registrations.views.attempt_organization_registration_notification")
    @patch("organization_registrations.storage.media_filesystem_writable", return_value=False)
    @patch("organization_registrations.storage.is_s3_configured", return_value=False)
    @patch("organization_registrations.storage.is_boto3_available", return_value=True)
    def test_serverless_without_logo_succeeds_without_s3(
        self, _boto, _cfg, _writable, mock_notify
    ):
        payload = _payload()
        del payload["logo"]
        response = self.client.post(URL, payload, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertTrue(OrganizationRegistration.objects.exists())
        mock_notify.assert_called_once()
