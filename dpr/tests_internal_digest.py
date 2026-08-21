"""Tests for protected DPR executive digest scheduler endpoint + shared service."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from dpr.models import DailyProgressReport
from dpr.services.executive_digest import (
    _idempotency_key,
    send_dpr_executive_digest,
)
from projects.models import Project


@override_settings(
    DPR_EMAIL_INLINE=True,
    DPR_DIGEST_ENABLED=True,
    DPR_EMAIL_ENABLED=True,
    DPR_DIGEST_CRON_SECRET="test-cron-secret-value-32chars!!",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_TRANSPORT="smtp",
    BREVO_API_KEY="",
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "dpr-digest-internal-tests",
        }
    },
)
class DprExecutiveDigestInternalApiTests(TestCase):
    URL = "/api/internal/dpr/executive-digest/"

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.pmc_group, _ = Group.objects.get_or_create(name="PMC Head")
        self.ho_group, _ = Group.objects.get_or_create(name="Head Office")
        self.pmc = User.objects.create_user(
            username="api_pmc",
            email="api.pmc@example.com",
            password="x",
        )
        self.pmc.groups.add(self.pmc_group)
        self.ho = User.objects.create_user(
            username="api_ho",
            email="api.ho@example.com",
            password="x",
        )
        self.ho.groups.add(self.ho_group)
        Project.objects.create(name="API Digest Active", status="active")

    def test_missing_secret_config_returns_503(self):
        with override_settings(DPR_DIGEST_CRON_SECRET=""):
            response = self.client.post(self.URL, {}, format="json")
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["message"], "Digest scheduler is not configured.")

    def test_invalid_secret_returns_401(self):
        response = self.client.post(
            self.URL,
            {},
            format="json",
            HTTP_X_CRON_SECRET="wrong-secret",
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data["message"], "Unauthorized.")

    def test_get_rejected(self):
        response = self.client.get(
            self.URL,
            HTTP_X_CRON_SECRET="test-cron-secret-value-32chars!!",
        )
        self.assertEqual(response.status_code, 405)

    def test_valid_secret_no_jwt_queues_digest(self):
        response = self.client.post(
            self.URL,
            {},
            format="json",
            HTTP_X_CRON_SECRET="test-cron-secret-value-32chars!!",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        self.assertIn(response.data["data"]["status"], ("sent", "queued"))
        self.assertEqual(len(mail.outbox), 1)
        recipients = mail.outbox[0].to
        self.assertIn("api.pmc@example.com", recipients)
        self.assertIn("api.ho@example.com", recipients)

    def test_already_processed_idempotent(self):
        headers = {"HTTP_X_CRON_SECRET": "test-cron-secret-value-32chars!!"}
        first = self.client.post(self.URL, {}, format="json", **headers)
        self.assertEqual(first.status_code, 200)
        second = self.client.post(self.URL, {}, format="json", **headers)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.data["data"]["status"], "already_processed")
        self.assertEqual(len(mail.outbox), 1)

    def test_failed_digest_can_retry(self):
        key = _idempotency_key(date.today())
        # Use business date from service after a controlled failure mark.
        from dpr.services.executive_digest import business_localdate

        key = _idempotency_key(business_localdate())
        cache.set(key, "failed", timeout=60)
        response = self.client.post(
            self.URL,
            {},
            format="json",
            HTTP_X_CRON_SECRET="test-cron-secret-value-32chars!!",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(response.data["data"]["status"], ("sent", "queued"))

    def test_running_returns_409(self):
        from dpr.services.executive_digest import business_localdate

        cache.set(_idempotency_key(business_localdate()), "running", timeout=60)
        response = self.client.post(
            self.URL,
            {},
            format="json",
            HTTP_X_CRON_SECRET="test-cron-secret-value-32chars!!",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["data"]["status"], "running")
        self.assertEqual(len(mail.outbox), 0)

    def test_concurrent_duplicate_triggers_only_one_send(self):
        """
        Simulate a race with cache.add semantics (thread pool + TestCase
        transactions cannot see fixture rows in worker threads).
        """
        from dpr.services.executive_digest import _acquire_idempotency, business_localdate

        day = business_localdate()
        first = _acquire_idempotency(day)
        second = _acquire_idempotency(day)
        self.assertTrue(first["ok"])
        self.assertFalse(second["ok"])
        self.assertEqual(second["status"], "running")

        # First request completes send; second API call sees completed.
        with patch(
            "dpr.services.executive_digest.send_dpr_executive_digest",
            wraps=send_dpr_executive_digest,
        ):
            # Mark completed as the service would after a successful queue/send.
            from dpr.services.executive_digest import _mark_completed

            _mark_completed(first["key"])

        response = self.client.post(
            self.URL,
            {},
            format="json",
            HTTP_X_CRON_SECRET="test-cron-secret-value-32chars!!",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["status"], "already_processed")
        self.assertEqual(len(mail.outbox), 0)

    def test_response_does_not_include_emails(self):
        response = self.client.post(
            self.URL,
            {},
            format="json",
            HTTP_X_CRON_SECRET="test-cron-secret-value-32chars!!",
        )
        payload = str(response.data)
        self.assertNotIn("api.pmc@example.com", payload)
        self.assertNotIn("@example.com", payload)

    @override_settings(DPR_DIGEST_CRON_SECRET="test-cron-secret-value-32chars!!")
    def test_wrong_secret_does_not_trigger(self):
        with patch(
            "dpr.internal_views.send_dpr_executive_digest"
        ) as mock_send:
            response = self.client.post(
                self.URL,
                {},
                format="json",
                HTTP_X_CRON_SECRET="nope",
            )
        self.assertEqual(response.status_code, 401)
        mock_send.assert_not_called()


@override_settings(
    DPR_EMAIL_INLINE=True,
    DPR_DIGEST_ENABLED=True,
    DPR_EMAIL_ENABLED=True,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_TRANSPORT="smtp",
    BREVO_API_KEY="",
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "dpr-digest-service-tests",
        }
    },
)
class DprExecutiveDigestServiceCompatTests(TestCase):
    def setUp(self):
        cache.clear()
        group, _ = Group.objects.get_or_create(name="PMC Head")
        user = User.objects.create_user(
            username="svc_pmc",
            email="svc.pmc@example.com",
            password="x",
        )
        user.groups.add(group)
        Project.objects.create(name="Svc Digest Project", status="active")

    def test_management_command_still_works(self):
        from django.core.management import call_command
        from io import StringIO

        out = StringIO()
        call_command(
            "send_dpr_executive_digest",
            "--date",
            "2026-08-21",
            "--force",
            stdout=out,
        )
        self.assertIn("sent", out.getvalue())
        self.assertEqual(len(mail.outbox), 1)

    def test_force_allows_resend(self):
        send_dpr_executive_digest(report_date=date(2026, 8, 21), force=True)
        self.assertEqual(len(mail.outbox), 1)
        send_dpr_executive_digest(report_date=date(2026, 8, 21), force=True)
        self.assertEqual(len(mail.outbox), 2)

    def test_notify_wrapper_delegates(self):
        from services.notifications import notify_dpr_executive_digest

        result = notify_dpr_executive_digest(
            report_date=date(2026, 8, 22),
            dry_run=True,
        )
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(len(mail.outbox), 0)

    def test_pmc_head_included_in_digest_recipients(self):
        from dpr.services.digest import resolve_digest_recipients, summarize_digest_recipients
        from services.notifications import _filter_event_email_recipients

        recipients = resolve_digest_recipients()
        summary = summarize_digest_recipients(recipients)
        self.assertGreaterEqual(summary["pmc_head_count"], 1)
        # Event filter removes PMC Head; digest must NOT use that filter.
        filtered = _filter_event_email_recipients(recipients)
        self.assertLess(len(filtered), len(recipients))
        self.assertTrue(any(u.groups.filter(name="PMC Head").exists() for u in recipients))

    def test_async_queue_does_not_mark_completed_before_send(self):
        from dpr.services.executive_digest import _idempotency_key

        with override_settings(DPR_EMAIL_INLINE=False):
            with patch("dpr.tasks.submit_email_job") as mock_submit:
                mock_submit.return_value = object()  # pretend queued Future
                result = send_dpr_executive_digest(
                    report_date=date(2026, 8, 23),
                    force=True,
                    source="test_async",
                )
                self.assertEqual(result["status"], "queued")
                self.assertEqual(cache.get(_idempotency_key(date(2026, 8, 23))), "running")
                mock_submit.assert_called_once()
