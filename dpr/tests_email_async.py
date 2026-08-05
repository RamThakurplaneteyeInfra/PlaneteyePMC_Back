"""
Tests: DPR SMTP emails via ThreadPoolExecutor after commit; WebSockets stay sync.
"""

from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import transaction
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.test_auth import authenticate_client
from dpr.models import DailyProgressReport, DPRActivity
from dpr.tasks import (
    send_dpr_approved_email,
    send_dpr_coordinator_approval_email,
    send_dpr_pmc_head_approval_email,
    send_dpr_rejection_email,
    send_dpr_resubmission_email,
    send_dpr_submission_email,
    send_dpr_team_leader_approval_email,
)
from monthly_scope.models import MonthlyScopeWork, ScopeCategory, ScopeSubCategory
from projects.models import Project
from services.notifications import (
    notify_dpr_approved,
    notify_dpr_approved_by_role,
    notify_dpr_rejected,
    notify_dpr_rejected_by_role,
    notify_dpr_submitted,
)


@override_settings(
    DPR_EMAIL_INLINE=True,
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "dpr-email-thread-tests",
        }
    },
)
class DprEmailThreadAsyncTests(TestCase):
    def setUp(self):
        cache.clear()
        self.tl = User.objects.create_user(
            username="async_tl",
            email="tl@example.com",
            password="testpass123",
            first_name="Team",
            last_name="Lead",
        )
        self.coord = User.objects.create_user(
            username="async_coord",
            email="coord@example.com",
            password="testpass123",
        )
        self.pmc = User.objects.create_user(
            username="async_pmc",
            email="pmc@example.com",
            password="testpass123",
        )
        self.se = User.objects.create_user(
            username="async_se",
            email="se@example.com",
            password="testpass123",
        )
        self.admin = User.objects.create_superuser(
            username="async_admin",
            email="admin@example.com",
            password="testpass123",
        )
        self.project = Project.objects.create(
            name="Async Email Project",
            status="active",
            team_lead=self.tl,
            pmc_head=self.pmc,
        )
        self.project.coordinators.add(self.coord)
        self.category = ScopeCategory.objects.create(name="AsyncCat")
        self.subcategory = ScopeSubCategory.objects.create(
            category=self.category, name="AsyncSub"
        )
        self.scope = MonthlyScopeWork.objects.create(
            project=self.project,
            category=self.category,
            subcategory=self.subcategory,
            month=date(2026, 8, 1),
            unit="Nos",
            planned_quantity=100,
            created_by=self.admin,
        )
        self.dpr = DailyProgressReport.objects.create(
            project_name=self.project.name,
            job_no="J1",
            report_date=date(2026, 8, 5),
            issued_by="SE",
            designation="Site Engineer",
            status=DailyProgressReport.Status.DRAFT,
            submitted_by=self.se,
            created_by=self.se,
            current_approver_role="Team Leader",
        )
        DPRActivity.objects.create(
            dpr=self.dpr,
            scope=self.scope,
            executed_quantity=5,
        )
        self.client = APIClient()
        authenticate_client(self.client, username="async_admin", password="testpass123")

    @patch("services.email_utils.send_html_email", return_value=True)
    @patch("services.notifications.send_websocket_notification")
    def test_submission_email(self, mock_ws, mock_email):
        self.dpr.status = DailyProgressReport.Status.PENDING_TEAM_LEAD
        self.dpr.current_approver_role = "Team Leader"
        self.dpr.save()

        with self.captureOnCommitCallbacks(execute=True):
            notify_dpr_submitted(self.dpr)

        self.assertTrue(mock_ws.called)
        mock_email.assert_called_once()
        self.assertEqual(mock_email.call_args.kwargs.get("template_name"), "dpr_submitted")

    @patch("services.email_utils.send_html_email", return_value=True)
    @patch("services.notifications.send_websocket_notification")
    def test_resubmission_email(self, mock_ws, mock_email):
        self.dpr.status = DailyProgressReport.Status.PENDING_TEAM_LEAD
        self.dpr.current_approver_role = "Team Leader"
        self.dpr.save()

        with self.captureOnCommitCallbacks(execute=True):
            notify_dpr_submitted(self.dpr, is_resubmit=True)

        self.assertTrue(mock_ws.called)
        mock_email.assert_called_once()
        self.assertEqual(mock_email.call_args.kwargs.get("template_name"), "dpr_submitted")

    @patch("services.email_utils.send_html_email", return_value=True)
    @patch("services.notifications.send_websocket_notification")
    def test_team_leader_approval_email(self, mock_ws, mock_email):
        with self.captureOnCommitCallbacks(execute=True):
            notify_dpr_approved_by_role(self.dpr, "Team Leader")

        self.assertTrue(mock_ws.called)
        mock_email.assert_called_once()
        self.assertEqual(mock_email.call_args.kwargs.get("template_name"), "dpr_approved")

    @patch("services.email_utils.send_html_email", return_value=True)
    @patch("services.notifications.send_websocket_notification")
    def test_coordinator_approval_email(self, mock_ws, mock_email):
        with self.captureOnCommitCallbacks(execute=True):
            notify_dpr_approved_by_role(self.dpr, "PMC Manager")

        self.assertTrue(mock_ws.called)
        mock_email.assert_called_once()
        self.assertEqual(mock_email.call_args.kwargs.get("template_name"), "dpr_approved")

    @patch("services.email_utils.send_html_email", return_value=True)
    @patch("services.notifications.send_websocket_notification")
    def test_pmc_head_approval_email(self, mock_ws, mock_email):
        with self.captureOnCommitCallbacks(execute=True):
            notify_dpr_approved_by_role(self.dpr, "PMC Head")

        self.assertTrue(mock_ws.called)
        mock_email.assert_called_once()
        self.assertEqual(mock_email.call_args.kwargs.get("template_name"), "dpr_approved")

    @patch("services.email_utils.send_html_email", return_value=True)
    @patch("services.notifications.send_websocket_notification")
    def test_rejection_email(self, mock_ws, mock_email):
        self.dpr.rejection_reason = "Needs rework"
        self.dpr.rejected_by = self.tl
        self.dpr.save()

        with self.captureOnCommitCallbacks(execute=True):
            notify_dpr_rejected_by_role(self.dpr, "Team Leader")

        self.assertTrue(mock_ws.called)
        mock_email.assert_called_once()
        self.assertEqual(mock_email.call_args.kwargs.get("template_name"), "dpr_rejected")

    @patch("services.email_utils.send_html_email", return_value=True)
    @patch("services.notifications.send_websocket_notification")
    def test_legacy_approve_reject(self, mock_ws, mock_email):
        with self.captureOnCommitCallbacks(execute=True):
            notify_dpr_approved(self.dpr)
        self.assertEqual(mock_email.call_count, 1)

        cache.clear()
        mock_email.reset_mock()
        self.dpr.rejection_reason = "x"
        self.dpr.save(update_fields=["rejection_reason"])
        with self.captureOnCommitCallbacks(execute=True):
            notify_dpr_rejected(self.dpr)
        self.assertEqual(mock_email.call_count, 1)

    def test_deduplicates(self):
        with patch("services.email_utils.send_html_email", return_value=True) as mock_email:
            r1 = send_dpr_team_leader_approval_email(
                dpr_id=self.dpr.id, recipient_ids=[self.se.id]
            )
            r2 = send_dpr_team_leader_approval_email(
                dpr_id=self.dpr.id, recipient_ids=[self.se.id]
            )
            self.assertEqual(r1["status"], "sent")
            self.assertEqual(r2["status"], "skipped_duplicate")
            self.assertEqual(mock_email.call_count, 1)

        cache.clear()
        with patch("services.email_utils.send_html_email", return_value=True) as mock_email:
            send_dpr_coordinator_approval_email(
                dpr_id=self.dpr.id, recipient_ids=[self.se.id]
            )
            send_dpr_pmc_head_approval_email(
                dpr_id=self.dpr.id, recipient_ids=[self.se.id]
            )
            send_dpr_rejection_email(
                dpr_id=self.dpr.id, recipient_ids=[self.se.id], role="Team Leader"
            )
            send_dpr_resubmission_email(
                dpr_id=self.dpr.id,
                submitted_by_id=self.se.id,
                recipient_ids=[self.tl.id],
            )
            send_dpr_submission_email(
                dpr_id=self.dpr.id,
                submitted_by_id=self.se.id,
                recipient_ids=[self.tl.id],
            )
            send_dpr_approved_email(dpr_id=self.dpr.id, recipient_ids=[self.se.id])
            self.assertEqual(mock_email.call_count, 6)

    @patch("services.email_utils.send_html_email", return_value=True)
    @patch("dpr.email_executor.submit_email_job")
    @patch("services.notifications.send_websocket_notification")
    def test_rollback_does_not_queue_email(self, mock_ws, mock_submit, mock_email):
        try:
            with transaction.atomic():
                notify_dpr_rejected_by_role(self.dpr, "Team Leader")
                raise RuntimeError("force rollback")
        except RuntimeError:
            pass

        mock_submit.assert_not_called()
        mock_email.assert_not_called()
        self.assertTrue(mock_ws.called)

    @patch("services.email_utils.send_html_email", return_value=True)
    @patch("services.notifications.send_websocket_notification")
    def test_submit_api_resubmit_queues_email(self, mock_ws, mock_email):
        self.dpr.status = DailyProgressReport.Status.REJECTED
        self.dpr.rejection_reason = "fix"
        self.dpr.save(update_fields=["status", "rejection_reason"])

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/api/dpr/{self.dpr.id}/submit/", {}, format="json"
            )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(mock_email.called)
        self.assertEqual(mock_email.call_args.kwargs.get("template_name"), "dpr_submitted")

    @patch("services.email_utils.send_html_email", return_value=True)
    @patch("services.notifications.send_websocket_notification")
    def test_approve_team_lead_api_queues_emails(self, mock_ws, mock_email):
        self.dpr.status = DailyProgressReport.Status.PENDING_TEAM_LEAD
        self.dpr.current_approver_role = "Team Leader"
        self.dpr.save()

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/api/dpr/{self.dpr.id}/approve_team_lead/", {}, format="json"
            )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertGreaterEqual(mock_email.call_count, 1)
        self.assertTrue(mock_ws.called)
        templates = [c.kwargs.get("template_name") for c in mock_email.call_args_list]
        self.assertIn("dpr_approved", templates)
        self.assertIn("dpr_submitted", templates)

    @patch("dpr.tasks.time.sleep")
    @patch("services.email_utils.send_html_email", side_effect=RuntimeError("smtp down"))
    def test_email_failure_retries_then_fails_softly(self, mock_email, mock_sleep):
        cache.clear()
        result = send_dpr_rejection_email(
            dpr_id=self.dpr.id,
            recipient_ids=[self.se.id],
            role="Team Leader",
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(mock_email.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)
        mock_sleep.assert_any_call(1)
        mock_sleep.assert_any_call(2)
