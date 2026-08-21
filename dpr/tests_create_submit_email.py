"""
DPR create vs submit email flow:

- NEW DPR CREATE → pending_team_lead → one initial submission email
- REJECTED → /submit/ → one resubmission email
- pending/approved → /submit/ → 400, no email
"""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.db import transaction
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.test_auth import authenticate_client
from dpr.models import DailyProgressReport
from dpr.tasks import send_dpr_resubmission_email, send_dpr_submission_email
from monthly_scope.models import MonthlyScopeWork, ScopeCategory, ScopeSubCategory
from projects.models import Project
from services.notifications import notify_dpr_submitted


@override_settings(
    DPR_EMAIL_INLINE=True,
    EMAIL_TRANSPORT="smtp",
    BREVO_API_KEY="",
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "dpr-create-submit-email",
        }
    },
)
class DprCreateSubmitEmailFlowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.tl = User.objects.create_user(
            username="flow_tl", email="flow_tl@example.com", password="x"
        )
        Group.objects.get_or_create(name="Team Leader")[0].user_set.add(self.tl)
        self.se = User.objects.create_user(
            username="flow_se", email="flow_se@example.com", password="x"
        )
        Group.objects.get_or_create(name="Site Engineer")[0].user_set.add(self.se)
        self.admin = User.objects.create_superuser(
            username="flow_admin", email="flow_admin@example.com", password="x"
        )
        self.project = Project.objects.create(
            name="Create Submit Email Project",
            status="active",
            team_lead=self.tl,
        )
        self.category = ScopeCategory.objects.create(name="FlowCat")
        self.subcategory = ScopeSubCategory.objects.create(
            name="FlowSub", category=self.category
        )
        self.scope = MonthlyScopeWork.objects.create(
            project=self.project,
            category=self.category,
            subcategory=self.subcategory,
            month=date(2026, 8, 1),
            unit="m",
            planned_quantity=100,
            created_by=self.admin,
        )
        self.client = APIClient()
        authenticate_client(self.client, username="flow_admin", password="x")

    def _payload(self, report_date: str = "2026-08-21"):
        return {
            "project_name": self.project.name,
            "job_no": "FLOW-1",
            "report_date": report_date,
            "issued_by": "SE",
            "designation": "Site Engineer",
            "activities": [
                {
                    "scope": self.scope.id,
                    "executed_quantity": "2.00",
                    "next_day_planned_work": "Continue",
                    "remarks": "ok",
                }
            ],
        }

    def _queued_fns(self, mock_submit_job):
        return [c.args[0] for c in mock_submit_job.call_args_list]

    @patch("services.notifications.send_websocket_notification")
    @patch("dpr.tasks.submit_email_job")
    def test_new_dpr_create_queues_initial_submission(self, mock_job, mock_ws):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post("/api/dpr/", self._payload(), format="json")

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(
            response.data["status"], DailyProgressReport.Status.PENDING_TEAM_LEAD
        )
        queued = self._queued_fns(mock_job)
        self.assertEqual(len(queued), 1)
        self.assertIs(queued[0], send_dpr_submission_email)
        self.assertEqual(mock_job.call_args.args[1]["dpr_id"], response.data["id"])

    @patch("services.notifications.send_websocket_notification")
    @patch("dpr.tasks.submit_email_job")
    def test_rejected_submit_queues_resubmission(self, mock_job, mock_ws):
        dpr = DailyProgressReport.objects.create(
            project_name=self.project.name,
            job_no="FLOW-R",
            report_date=date(2026, 8, 20),
            issued_by="SE",
            designation="Site Engineer",
            status=DailyProgressReport.Status.REJECTED,
            submitted_by=self.se,
            created_by=self.se,
            rejection_reason="fix",
            current_approver_role="Team Leader",
        )

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(f"/api/dpr/{dpr.id}/submit/", {}, format="json")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            response.data["status"], DailyProgressReport.Status.PENDING_TEAM_LEAD
        )
        queued = self._queued_fns(mock_job)
        self.assertEqual(len(queued), 1)
        self.assertIs(queued[0], send_dpr_resubmission_email)

    @patch("services.notifications.send_websocket_notification")
    @patch("dpr.tasks.submit_email_job")
    def test_pending_submit_rejected_no_email(self, mock_job, mock_ws):
        dpr = DailyProgressReport.objects.create(
            project_name=self.project.name,
            job_no="FLOW-P",
            report_date=date(2026, 8, 19),
            issued_by="SE",
            designation="Site Engineer",
            status=DailyProgressReport.Status.PENDING_TEAM_LEAD,
            submitted_by=self.se,
            created_by=self.se,
            current_approver_role="Team Leader",
        )
        response = self.client.post(f"/api/dpr/{dpr.id}/submit/", {}, format="json")
        self.assertEqual(response.status_code, 400)
        mock_job.assert_not_called()

    @patch("services.notifications.send_websocket_notification")
    @patch("dpr.tasks.submit_email_job")
    def test_approved_submit_rejected_no_email(self, mock_job, mock_ws):
        dpr = DailyProgressReport.objects.create(
            project_name=self.project.name,
            job_no="FLOW-A",
            report_date=date(2026, 8, 18),
            issued_by="SE",
            designation="Site Engineer",
            status=DailyProgressReport.Status.APPROVED,
            submitted_by=self.se,
            created_by=self.se,
            current_approver_role="",
        )
        response = self.client.post(f"/api/dpr/{dpr.id}/submit/", {}, format="json")
        self.assertEqual(response.status_code, 400)
        mock_job.assert_not_called()

    @patch("services.notifications.send_websocket_notification")
    @patch("dpr.tasks.submit_email_job")
    def test_create_rollback_does_not_queue_email(self, mock_job, mock_ws):
        dpr = DailyProgressReport.objects.create(
            project_name=self.project.name,
            job_no="FLOW-RB",
            report_date=date(2026, 8, 17),
            issued_by="SE",
            designation="Site Engineer",
            status=DailyProgressReport.Status.PENDING_TEAM_LEAD,
            submitted_by=self.se,
            created_by=self.se,
            current_approver_role="Team Leader",
        )
        try:
            with transaction.atomic():
                notify_dpr_submitted(dpr, is_resubmit=False)
                raise RuntimeError("force rollback")
        except RuntimeError:
            pass

        mock_job.assert_not_called()

    @patch("services.notifications.send_websocket_notification")
    @patch("dpr.tasks.submit_email_job")
    def test_create_then_submit_does_not_duplicate_email(self, mock_job, mock_ws):
        with self.captureOnCommitCallbacks(execute=True):
            created = self.client.post(
                "/api/dpr/", self._payload("2026-08-22"), format="json"
            )

        self.assertEqual(created.status_code, 201, created.content)
        self.assertEqual(len(self._queued_fns(mock_job)), 1)
        self.assertIs(self._queued_fns(mock_job)[0], send_dpr_submission_email)

        submit = self.client.post(
            f"/api/dpr/{created.data['id']}/submit/", {}, format="json"
        )
        self.assertEqual(submit.status_code, 400)
        self.assertEqual(len(self._queued_fns(mock_job)), 1)
