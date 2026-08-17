"""
Hardening tests: metrics, health API, load bursts, SMTP timeout wiring.
"""

from __future__ import annotations

from concurrent.futures import wait
from datetime import date
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
