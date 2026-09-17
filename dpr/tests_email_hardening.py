"""
Hardening tests: metrics, health API, load bursts, SMTP timeout wiring.
"""

from __future__ import annotations

import threading
import time
import io
import json
import urllib.error
from concurrent.futures import wait
from datetime import date
from smtplib import SMTPAuthenticationError
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient

from core.test_auth import authenticate_client
from dpr.email_executor import (
    EMAIL_EXECUTOR,
    get_email_pool_snapshot,
    reset_metrics_for_tests,
    submit_email_job,
)
from dpr.models import DailyProgressReport
from dpr.tasks import send_dpr_submission_email
from projects.models import Project


@override_settings(
    DPR_EMAIL_INLINE=True,
    EMAIL_TIMEOUT=15,
    EMAIL_TRANSPORT="smtp",
    BREVO_API_KEY="",
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "dpr-email-hardening",
        }
    },
)
class DprEmailHardeningTests(TestCase):
    def setUp(self):
        cache.clear()
        reset_metrics_for_tests()
        self.tl = User.objects.create_user(
            username="hard_tl", email="tl@example.com", password="x"
        )
        self.se = User.objects.create_user(
            username="hard_se", email="se@example.com", password="x"
        )
        self.admin = User.objects.create_superuser(
            username="hard_admin", email="admin@example.com", password="x"
        )
        self.engineer = User.objects.create_user(
            username="hard_eng", email="eng@example.com", password="x"
        )
        Group.objects.get_or_create(name="Site Engineer")[0].user_set.add(self.engineer)
        self.pmc = User.objects.create_user(
            username="hard_pmc", email="pmc@example.com", password="x"
        )
        Group.objects.get_or_create(name="PMC Head")[0].user_set.add(self.pmc)
        self.project = Project.objects.create(
            name="Hardening Email Project",
            status="active",
            team_lead=self.tl,
        )
        self.dpr = DailyProgressReport.objects.create(
            project_name=self.project.name,
            job_no="H1",
            report_date=date(2026, 8, 5),
            issued_by="SE",
            designation="Site Engineer",
            status=DailyProgressReport.Status.PENDING_TEAM_LEAD,
            submitted_by=self.se,
            created_by=self.se,
            current_approver_role="Team Leader",
        )
        self.client = APIClient()

    @patch("services.email_utils.send_html_email", return_value=True)
    def test_metrics_increment_on_success(self, mock_email):
        result = send_dpr_submission_email(
            dpr_id=self.dpr.id,
            submitted_by_id=self.se.id,
            recipient_ids=[self.tl.id],
        )
        cache.clear()
        reset_metrics_for_tests()
        submit_email_job(
            send_dpr_submission_email,
            {
                "dpr_id": self.dpr.id,
                "submitted_by_id": self.se.id,
                "recipient_ids": [self.tl.id],
            },
        )
        snap = get_email_pool_snapshot()["thread_pool"]
        self.assertEqual(snap["emails_queued"], 1)
        self.assertEqual(snap["completed_tasks"], 1)
        self.assertEqual(snap["failed_tasks"], 0)
        self.assertEqual(result["status"], "sent")

    @patch("dpr.tasks.time.sleep")
    @patch("services.email_utils.send_html_email", side_effect=RuntimeError("smtp down"))
    def test_metrics_increment_on_failure(self, mock_email, mock_sleep):
        reset_metrics_for_tests()
        submit_email_job(
            send_dpr_submission_email,
            {
                "dpr_id": self.dpr.id,
                "submitted_by_id": self.se.id,
                "recipient_ids": [self.tl.id],
            },
        )
        snap = get_email_pool_snapshot()["thread_pool"]
        self.assertEqual(snap["failed_tasks"], 1)
        self.assertEqual(mock_email.call_count, 3)

    def test_health_api_rbac(self):
        authenticate_client(self.client, username="hard_eng", password="x")
        denied = self.client.get("/api/system/background-tasks/")
        self.assertEqual(denied.status_code, 403)

        authenticate_client(self.client, username="hard_pmc", password="x")
        ok = self.client.get("/api/system/background-tasks/")
        self.assertEqual(ok.status_code, 200, ok.content)
        body = ok.json()
        self.assertTrue(body.get("success"))
        pool = body["data"]["thread_pool"]
        self.assertIn("max_workers", pool)
        self.assertIn("completed_tasks", pool)
        self.assertEqual(pool["max_workers"], 4)

    @patch("services.email_utils.get_connection")
    @patch("services.email_utils.EmailMultiAlternatives")
    @patch("services.email_utils.render_to_string", return_value="<html/>")
    def test_smtp_uses_timeout(self, mock_render, mock_message_cls, mock_conn):
        from services.email_utils import send_html_email

        mock_conn.return_value = object()
        mock_message = mock_message_cls.return_value
        mock_message.send.return_value = 1
        ok = send_html_email(
            subject="t",
            template_name="dpr_submitted",
            context={},
            recipient_list=["a@example.com"],
        )
        self.assertTrue(ok)
        mock_conn.assert_called()
        kwargs = mock_conn.call_args.kwargs
        self.assertEqual(kwargs.get("timeout"), 15.0)
        mock_message.attach_alternative.assert_called_once_with("<html/>", "text/html")
        mock_message.send.assert_called_once_with(fail_silently=False)

    @patch("services.email_utils.get_connection")
    @patch("services.email_utils.EmailMultiAlternatives")
    @patch("services.email_utils.render_to_string", return_value="<html/>")
    def test_send_html_email_dedupes_recipients(self, mock_render, mock_message_cls, mock_conn):
        from services.email_utils import send_html_email

        mock_conn.return_value = object()
        mock_message = mock_message_cls.return_value
        mock_message.send.return_value = 1
        send_html_email(
            subject="t",
            template_name="dpr_submitted",
            context={},
            recipient_list=["A@example.com", "a@example.com", "b@example.com", ""],
        )
        kwargs = mock_message_cls.call_args.kwargs
        self.assertEqual(kwargs.get("to"), ["A@example.com", "b@example.com"])

    @override_settings(
        EMAIL_TRANSPORT="brevo_api",
        BREVO_API_KEY="xkeysib-test-key",
        BREVO_FROM_NAME="PMC Test",
        DEFAULT_FROM_EMAIL="from@example.com",
        EMAIL_TIMEOUT=12,
    )
    @patch("services.email_utils.render_to_string", return_value="<html>hi</html>")
    @patch("services.email_utils.urllib.request.urlopen")
    def test_brevo_api_transport_posts_payload(self, mock_urlopen, mock_render):
        from services.email_utils import send_html_email

        response = mock_urlopen.return_value.__enter__.return_value
        response.status = 201
        response.read.return_value = b'{"messageId":"<test-id>"}'
        ok = send_html_email(
            subject="DPR Submitted",
            template_name="dpr_submitted",
            context={},
            recipient_list=["a@example.com", "a@example.com", "b@example.com"],
        )
        self.assertTrue(ok)
        mock_urlopen.assert_called_once()
        request = mock_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.brevo.com/v3/smtp/email")
        self.assertEqual(request.get_header("Api-key"), "xkeysib-test-key")
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["subject"], "DPR Submitted")
        self.assertEqual(
            [row["email"] for row in body["to"]],
            ["a@example.com", "b@example.com"],
        )
        self.assertEqual(body["sender"]["email"], "from@example.com")

    @override_settings(EMAIL_TRANSPORT="brevo_api", BREVO_API_KEY="xkeysib-test-key")
    @patch("services.email_utils.render_to_string", return_value="<html/>")
    @patch("services.email_utils.urllib.request.urlopen")
    def test_brevo_api_auth_failure_is_not_retryable(self, mock_urlopen, mock_render):
        from services.email_utils import BrevoAPIError, is_retryable_smtp_error, send_html_email

        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://api.brevo.com/v3/smtp/email",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=io.BytesIO(b'{"message":"Key not found"}'),
        )
        with self.assertRaises(BrevoAPIError) as ctx:
            send_html_email(
                subject="t",
                template_name="dpr_submitted",
                context={},
                recipient_list=["a@example.com"],
            )
        self.assertFalse(is_retryable_smtp_error(ctx.exception))
        self.assertEqual(ctx.exception.status_code, 401)

    def test_test_email_backend_is_locmem(self):
        from django.conf import settings as django_settings

        self.assertEqual(
            django_settings.EMAIL_BACKEND,
            "django.core.mail.backends.locmem.EmailBackend",
        )

    def test_production_defaults_are_async_with_timeout(self):
        from django.conf import settings as django_settings

        self.assertEqual(django_settings.DPR_EMAIL_MAX_WORKERS, 4)
        self.assertEqual(django_settings.DPR_EMAIL_MAX_PENDING, 200)
        self.assertEqual(django_settings.EMAIL_TIMEOUT, 15)

    @patch("dpr.tasks.time.sleep")
    @patch(
        "services.email_utils.send_html_email",
        side_effect=SMTPAuthenticationError(535, b"auth failed"),
    )
    def test_permanent_smtp_failure_does_not_retry(self, mock_email, mock_sleep):
        cache.clear()
        result = send_dpr_submission_email(
            dpr_id=self.dpr.id,
            submitted_by_id=self.se.id,
            recipient_ids=[self.tl.id],
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result.get("retryable"), False)
        self.assertEqual(mock_email.call_count, 1)
        mock_sleep.assert_not_called()

    @patch("dpr.tasks.close_old_connections")
    @patch("services.email_utils.send_html_email", return_value=True)
    def test_inline_false_closes_db_connections(self, mock_email, mock_close):
        cache.clear()
        with override_settings(DPR_EMAIL_INLINE=False):
            result = send_dpr_submission_email(
                dpr_id=self.dpr.id,
                submitted_by_id=self.se.id,
                recipient_ids=[self.tl.id],
            )
        self.assertEqual(result["status"], "sent")
        self.assertGreaterEqual(mock_close.call_count, 2)

    def test_queue_capacity_drops_without_raising(self):
        reset_metrics_for_tests()
        with patch("dpr.email_executor._max_pending", return_value=0):
            future = submit_email_job(
                send_dpr_submission_email,
                {
                    "dpr_id": self.dpr.id,
                    "submitted_by_id": self.se.id,
                    "recipient_ids": [self.tl.id],
                },
            )
        self.assertIsNone(future)
        snap = get_email_pool_snapshot()["thread_pool"]
        self.assertEqual(snap["failed_tasks"], 1)

    @patch("services.email_utils.send_html_email", return_value=True)
    @patch("services.notifications.send_websocket_notification")
    def test_project_created_endpoint_does_not_send_smtp_inline(
        self, mock_ws, mock_email
    ):
        self.project.coordinators.add(self.tl)
        authenticate_client(self.client, username="hard_admin", password="x")
        response = self.client.post(
            "/api/notifications/project-created/",
            {"project_id": self.project.id},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        mock_email.assert_not_called()


@override_settings(
    DPR_EMAIL_INLINE=False,
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "dpr-email-latency",
        }
    },
)
class DprEmailApiLatencyTests(TransactionTestCase):
    """Prove HTTP returns before SMTP finishes (real threads, real on_commit)."""

    def setUp(self):
        cache.clear()
        reset_metrics_for_tests()
        self.tl = User.objects.create_user(
            username="lat_tl", email="lat_tl@example.com", password="x"
        )
        self.se = User.objects.create_user(
            username="lat_se", email="lat_se@example.com", password="x"
        )
        self.admin = User.objects.create_superuser(
            username="lat_admin", email="lat_admin@example.com", password="x"
        )
        self.project = Project.objects.create(
            name="Latency Email Project",
            status="active",
            team_lead=self.tl,
        )
        self.dpr = DailyProgressReport.objects.create(
            project_name=self.project.name,
            job_no="LAT1",
            report_date=date(2026, 8, 5),
            issued_by="SE",
            designation="Site Engineer",
            status=DailyProgressReport.Status.DRAFT,
            submitted_by=self.se,
            created_by=self.se,
            current_approver_role="Team Leader",
        )
        self.client = APIClient()
        authenticate_client(self.client, username="lat_admin", password="x")

    @patch("services.notifications.send_websocket_notification")
    def test_submit_api_does_not_wait_for_slow_smtp(self, mock_ws):
        smtp_started = threading.Event()
        smtp_release = threading.Event()
        send_times: list[float] = []

        def slow_send(*args, **kwargs):
            smtp_started.set()
            send_times.append(time.perf_counter())
            smtp_release.wait(timeout=5)
            return True

        with patch("services.email_utils.send_html_email", side_effect=slow_send) as mock_email:
            try:
                t0 = time.perf_counter()
                response = self.client.post(
                    f"/api/dpr/{self.dpr.id}/submit/", {}, format="json"
                )
                api_ms = (time.perf_counter() - t0) * 1000.0
                self.assertEqual(response.status_code, 200, response.content)
                # Request returned while the worker was still blocked in SMTP.
                self.assertFalse(smtp_release.is_set())
                self.assertLess(
                    api_ms,
                    4000,
                    f"API waited on SMTP: {api_ms:.1f}ms",
                )
                self.assertTrue(smtp_started.wait(timeout=5), "SMTP job never started")
            finally:
                smtp_release.set()
            deadline = time.time() + 8
            while mock_email.call_count == 0 and time.time() < deadline:
                time.sleep(0.05)
            self.assertEqual(mock_email.call_count, 1)
            self.assertGreater(api_ms, 0)

    @patch("services.notifications.send_websocket_notification")
    def test_submit_api_without_email_queue_is_similar_latency(self, mock_ws):
        with patch("dpr.tasks.submit_email_job") as mock_submit:
            t0 = time.perf_counter()
            response = self.client.post(
                f"/api/dpr/{self.dpr.id}/submit/", {}, format="json"
            )
            api_ms = (time.perf_counter() - t0) * 1000.0
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(mock_submit.called)
        self.assertLess(api_ms, 4000)


@override_settings(
    DPR_EMAIL_INLINE=False,
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "dpr-email-load",
        }
    },
)
class DprEmailLoadTests(TransactionTestCase):
    """Real threads need committed rows (TransactionTestCase)."""

    def setUp(self):
        cache.clear()
        reset_metrics_for_tests()
        self.tl = User.objects.create_user(
            username="load_tl", email="load_tl@example.com", password="x"
        )
        self.se = User.objects.create_user(
            username="load_se", email="load_se@example.com", password="x"
        )
        self.project = Project.objects.create(
            name="Load Email Project",
            status="active",
            team_lead=self.tl,
        )
        self.dpr = DailyProgressReport.objects.create(
            project_name=self.project.name,
            job_no="L1",
            report_date=date(2026, 8, 5),
            issued_by="SE",
            designation="Site Engineer",
            status=DailyProgressReport.Status.PENDING_TEAM_LEAD,
            submitted_by=self.se,
            created_by=self.se,
            current_approver_role="Team Leader",
        )

    @patch("services.email_utils.send_html_email", return_value=True)
    def test_load_burst_10_25_50(self, mock_email):
        for burst in (10, 25, 50):
            cache.clear()
            reset_metrics_for_tests()
            mock_email.reset_mock()
            futures = []
            for _ in range(burst):
                futures.append(
                    submit_email_job(
                        send_dpr_submission_email,
                        {
                            "dpr_id": self.dpr.id,
                            "submitted_by_id": self.se.id,
                            "recipient_ids": [self.tl.id],
                        },
                    )
                )
            real = [f for f in futures if f is not None]
            done, not_done = wait(real, timeout=60)
            self.assertFalse(not_done, f"timed out burst={burst}")
            snap = get_email_pool_snapshot()["thread_pool"]
            self.assertEqual(mock_email.call_count, 1, f"duplicates in burst={burst}")
            self.assertEqual(
                snap["completed_tasks"] + snap["skipped_duplicate"],
                burst,
            )
            self.assertLessEqual(len(getattr(EMAIL_EXECUTOR, "_threads", [])), 4)
