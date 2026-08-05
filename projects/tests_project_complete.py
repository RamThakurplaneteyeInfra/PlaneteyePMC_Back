"""Tests for POST /api/projects/{id}/complete/."""

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

    def test_ho_can_complete(self):
        authenticate_client(self.client, username="cmp_ho", password="Project@123")
        response = self.client.post(
            self._url(), {"completion_notes": "All deliverables done"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.project.refresh_from_db()
        self.assertEqual(self.project.status, "completed")
        self.assertIsNotNone(self.project.completed_at)
        self.assertEqual(self.project.completed_by_id, self.ho.id)
        self.assertEqual(self.project.completion_notes, "All deliverables done")

    def test_ceo_and_pmc_can_complete(self):
        authenticate_client(self.client, username="cmp_ceo", password="Project@123")
        p = Project.objects.create(name="CEO Complete Proj", status="active")
        self.assertEqual(
            self.client.post(self._url(p.id), {}, format="json").status_code,
            status.HTTP_200_OK,
        )

        authenticate_client(self.client, username="cmp_pmc", password="Project@123")
        p2 = Project.objects.create(name="PMC Complete Proj", status="active")
        self.assertEqual(
            self.client.post(self._url(p2.id), {}, format="json").status_code,
            status.HTTP_200_OK,
        )

    def test_tl_forbidden(self):
        authenticate_client(self.client, username="cmp_tl", password="Project@123")
        response = self.client.post(self._url(), {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.project.refresh_from_db()
        self.assertEqual(self.project.status, "active")

    def test_se_forbidden(self):
        authenticate_client(self.client, username="cmp_se", password="Project@123")
        self.assertEqual(
            self.client.post(self._url(), {}, format="json").status_code,
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
        response = self.client.post(self._url(), {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.project.refresh_from_db()
        self.assertEqual(self.project.status, "completed")

    def test_audit_and_notification(self):
        authenticate_client(self.client, username="cmp_ho", password="Project@123")
        before_audit = UserManagementAuditLog.objects.count()
        self.client.post(self._url(), {"completion_notes": "Done"}, format="json")
        self.assertGreater(UserManagementAuditLog.objects.count(), before_audit)
        self.assertTrue(
            Notification.objects.filter(
                project=self.project,
                notification_type=Notification.NOTIFICATION_TYPE_PROJECT_COMPLETED,
            ).exists()
        )

    def test_cache_invalidated(self):
        authenticate_client(self.client, username="cmp_ho", password="Project@123")
        v_before = get_list_cache_version("project_overview_v3")
        self.client.post(self._url(), {}, format="json")
        self.assertGreater(get_list_cache_version("project_overview_v3"), v_before)

    def test_overview_includes_completion_fields(self):
        authenticate_client(self.client, username="cmp_ho", password="Project@123")
        self.client.post(self._url(), {}, format="json")
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
        self.assertIsNotNone(row.get("completed_at"))
        self.assertIsNotNone(row.get("completed_by"))

    def test_write_blocked_after_completion(self):
        authenticate_client(self.client, username="cmp_ho", password="Project@123")
        self.client.post(self._url(), {}, format="json")
        # Patch project should be rejected as read-only
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
        response = self.client.post(self._url(), {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
