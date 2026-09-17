"""Tests for POST /api/projects/{id}/complete/ and complete-billing/."""

from datetime import date

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Notification, UserManagementAuditLog
from core.cache_keys import get_list_cache_version
from core.test_auth import authenticate_client
from dpr.models import DailyProgressReport
from projects.models import Project


class ProjectCompleteAPITest(APITestCase):
    def setUp(self):
        cache.clear()
        self.ho_group, _ = Group.objects.get_or_create(name="Head Office")
        self.ceo_group, _ = Group.objects.get_or_create(name="CEO")
        self.pmc_group, _ = Group.objects.get_or_create(name="PMC Head")
        self.tl_group, _ = Group.objects.get_or_create(name="Team Leader")
        self.se_group, _ = Group.objects.get_or_create(name="Site Engineer")

        self.ho = User.objects.create_user(username="cmp_ho", password="Project@123")
        self.ho.groups.add(self.ho_group)
        self.ceo = User.objects.create_user(username="cmp_ceo", password="Project@123")
        self.ceo.groups.add(self.ceo_group)
        self.pmc = User.objects.create_user(username="cmp_pmc", password="Project@123")
        self.pmc.groups.add(self.pmc_group)
        self.tl = User.objects.create_user(username="cmp_tl", password="Project@123")
        self.tl.groups.add(self.tl_group)
        self.se = User.objects.create_user(username="cmp_se", password="Project@123")
        self.se.groups.add(self.se_group)

        self.project = Project.objects.create(
            name="Completion Test Project",
            status="active",
            team_lead=self.tl,
        )

    def _url(self, pk=None):
        return f"/api/projects/{pk or self.project.id}/complete/"

    def _billing_url(self, pk=None):
        return f"/api/projects/{pk or self.project.id}/complete-billing/"

    def test_ho_can_complete_with_billing_pending(self):
        authenticate_client(self.client, username="cmp_ho", password="Project@123")
        response = self.client.post(
            self._url(),
            {
                "billing_status": "Pending",
                "completion_notes": "Civil work completed.",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(response.data["success"])
        data = response.data["data"]
        self.assertEqual(data["status"], "completed")
        self.assertEqual(data["billing_status"], "Pending")
        self.assertIsNone(data["billing_completed_at"])
        self.assertIsNone(data["billing_completed_by"])
        self.project.refresh_from_db()
        self.assertEqual(self.project.status, "completed")
        self.assertEqual(self.project.billing_status, Project.BILLING_STATUS_PENDING)
        self.assertIsNotNone(self.project.completed_at)
        self.assertEqual(self.project.completed_by_id, self.ho.id)
        self.assertEqual(self.project.completion_notes, "Civil work completed.")

    def test_complete_with_billing_completed(self):
        authenticate_client(self.client, username="cmp_ho", password="Project@123")
        response = self.client.post(
            self._url(),
            {
                "billing_status": "Completed",
                "completion_notes": "Project and billing completed.",
                "billing_completion_notes": "Final bill released.",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        data = response.data["data"]
        self.assertEqual(data["status"], "completed")
        self.assertEqual(data["billing_status"], "Completed")
        self.assertIsNotNone(data["billing_completed_at"])
        self.assertEqual(data["billing_completed_by"]["id"], self.ho.id)
        self.assertEqual(data["billing_completion_notes"], "Final bill released.")
        self.project.refresh_from_db()
        self.assertEqual(self.project.billing_status, Project.BILLING_STATUS_COMPLETED)

    def test_billing_status_required(self):
        authenticate_client(self.client, username="cmp_ho", password="Project@123")
        response = self.client.post(
            self._url(), {"completion_notes": "Missing billing"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.project.refresh_from_db()
        self.assertEqual(self.project.status, "active")

    def test_ceo_and_pmc_can_complete(self):
        authenticate_client(self.client, username="cmp_ceo", password="Project@123")
        p = Project.objects.create(name="CEO Complete Proj", status="active")
        self.assertEqual(
            self.client.post(
                self._url(p.id), {"billing_status": "Pending"}, format="json"
            ).status_code,
            status.HTTP_200_OK,
        )

        authenticate_client(self.client, username="cmp_pmc", password="Project@123")
        p2 = Project.objects.create(name="PMC Complete Proj", status="active")
        self.assertEqual(
            self.client.post(
                self._url(p2.id), {"billing_status": "Completed"}, format="json"
            ).status_code,
            status.HTTP_200_OK,
        )

    def test_tl_forbidden(self):
        authenticate_client(self.client, username="cmp_tl", password="Project@123")
        response = self.client.post(
            self._url(), {"billing_status": "Pending"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.project.refresh_from_db()
        self.assertEqual(self.project.status, "active")

    def test_se_forbidden(self):
        authenticate_client(self.client, username="cmp_se", password="Project@123")
        self.assertEqual(
            self.client.post(
                self._url(), {"billing_status": "Pending"}, format="json"
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_completes_even_with_pending_dpr(self):
        DailyProgressReport.objects.create(
            project_name=self.project.name,
            job_no="J1",
            report_date=date.today(),
            issued_by="SE",
            designation="SE",
            status=DailyProgressReport.Status.PENDING_TEAM_LEAD,
            submitted_by=self.se,
        )
        authenticate_client(self.client, username="cmp_ho", password="Project@123")
        response = self.client.post(
            self._url(), {"billing_status": "Pending"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.project.refresh_from_db()
        self.assertEqual(self.project.status, "completed")

    def test_audit_and_notification(self):
        authenticate_client(self.client, username="cmp_ho", password="Project@123")
        before_audit = UserManagementAuditLog.objects.count()
        self.client.post(
            self._url(),
            {"billing_status": "Pending", "completion_notes": "Done"},
            format="json",
        )
        self.assertGreater(UserManagementAuditLog.objects.count(), before_audit)
        self.assertTrue(
            Notification.objects.filter(
                project=self.project,
                notification_type=Notification.NOTIFICATION_TYPE_PROJECT_COMPLETED,
            ).exists()
        )

    def test_cache_invalidated(self):
        authenticate_client(self.client, username="cmp_ho", password="Project@123")
        v_before = get_list_cache_version("project_overview_v4")
        self.client.post(
            self._url(), {"billing_status": "Pending"}, format="json"
        )
        self.assertGreater(get_list_cache_version("project_overview_v4"), v_before)

    def test_overview_includes_completion_and_billing_fields(self):
        authenticate_client(self.client, username="cmp_ho", password="Project@123")
        self.client.post(
            self._url(), {"billing_status": "Pending"}, format="json"
        )
        response = self.client.get(
            "/api/projects/overview/?status=completed"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        row = next(
            (r for r in response.data["data"] if r["project_id"] == self.project.id),
            None,
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "completed")
        self.assertEqual(row["billing_status"], "Pending")
        self.assertIsNotNone(row.get("completed_at"))
        self.assertIsNotNone(row.get("completed_by"))

    def test_overview_billing_status_filter(self):
        authenticate_client(self.client, username="cmp_ho", password="Project@123")
        self.client.post(
            self._url(), {"billing_status": "Pending"}, format="json"
        )
        p2 = Project.objects.create(name="Billing Done Proj", status="active")
        self.client.post(
            self._url(p2.id), {"billing_status": "Completed"}, format="json"
        )

        pending = self.client.get(
            "/api/projects/overview/?status=completed&billing_status=Pending"
        )
        pending_ids = {r["project_id"] for r in pending.data["data"]}
        self.assertIn(self.project.id, pending_ids)
        self.assertNotIn(p2.id, pending_ids)

        done = self.client.get(
            "/api/projects/overview/?status=completed&billing_status=Completed"
        )
        done_ids = {r["project_id"] for r in done.data["data"]}
        self.assertIn(p2.id, done_ids)
        self.assertNotIn(self.project.id, done_ids)

    def test_write_blocked_after_completion(self):
        authenticate_client(self.client, username="cmp_ho", password="Project@123")
        self.client.post(
            self._url(), {"billing_status": "Pending"}, format="json"
        )
        response = self.client.patch(
            f"/api/projects/{self.project.id}/",
            {"location": "Should Fail"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_already_completed(self):
        self.project.status = "completed"
        self.project.save(update_fields=["status"])
        authenticate_client(self.client, username="cmp_ho", password="Project@123")
        response = self.client.post(
            self._url(), {"billing_status": "Pending"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_complete_billing_after_project_completion(self):
        authenticate_client(self.client, username="cmp_ho", password="Project@123")
        self.client.post(
            self._url(),
            {"billing_status": "Pending", "completion_notes": "Civil done"},
            format="json",
        )
        before_audit = UserManagementAuditLog.objects.count()
        response = self.client.post(
            self._billing_url(),
            {"billing_completion_notes": "Final bill released."},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(response.data["success"])
        data = response.data["data"]
        self.assertEqual(data["status"], "completed")
        self.assertEqual(data["billing_status"], "Completed")
        self.assertIsNotNone(data["billing_completed_at"])
        self.assertEqual(data["billing_completed_by"]["id"], self.ho.id)
        self.project.refresh_from_db()
        self.assertEqual(self.project.billing_status, Project.BILLING_STATUS_COMPLETED)
        self.assertEqual(
            self.project.billing_completion_notes, "Final bill released."
        )
        self.assertGreater(UserManagementAuditLog.objects.count(), before_audit)

    def test_complete_billing_blocked_before_project_completion(self):
        authenticate_client(self.client, username="cmp_ho", password="Project@123")
        response = self.client.post(
            self._billing_url(),
            {"billing_completion_notes": "Too early"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("completed", response.data["message"].lower())
        self.project.refresh_from_db()
        self.assertEqual(self.project.billing_status, Project.BILLING_STATUS_PENDING)

    def test_complete_billing_rbac(self):
        self.project.status = "completed"
        self.project.billing_status = Project.BILLING_STATUS_PENDING
        self.project.save(update_fields=["status", "billing_status"])
        authenticate_client(self.client, username="cmp_tl", password="Project@123")
        self.assertEqual(
            self.client.post(self._billing_url(), {}, format="json").status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_list_billing_status_filter(self):
        authenticate_client(self.client, username="cmp_ho", password="Project@123")
        self.client.post(
            self._url(), {"billing_status": "Pending"}, format="json"
        )
        response = self.client.get(
            "/api/projects/?status=completed&billing_status=Pending"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # DRF list may be paginated
        results = response.data.get("results", response.data)
        if isinstance(results, dict) and "data" in results:
            results = results["data"]
        ids = []
        if isinstance(results, list):
            for row in results:
                if isinstance(row, dict) and "id" in row:
                    ids.append(row["id"])
                    self.assertEqual(row.get("billing_status"), "Pending")
        self.assertIn(self.project.id, ids)
