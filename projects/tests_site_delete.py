"""Tests for Init List site deletion: DELETE /api/projects/init-list/{site_id}/."""

from datetime import date, timedelta

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserManagementAuditLog
from core.cache_keys import get_list_cache_version
from core.test_auth import authenticate_client
from operations.models import DailyProgressReport, Task
from projects.models import Project, Site


class InitListSiteDeleteTest(APITestCase):
    URL = "/api/projects/init-list/"

    def setUp(self):
        cache.clear()
        self.ho_group, _ = Group.objects.get_or_create(name="Head Office")
        self.ceo_group, _ = Group.objects.get_or_create(name="CEO")
        self.pmc_group, _ = Group.objects.get_or_create(name="PMC Head")
        self.tl_group, _ = Group.objects.get_or_create(name="Team Leader")
        self.se_group, _ = Group.objects.get_or_create(name="Site Engineer")
        self.qaqc_group, _ = Group.objects.get_or_create(name="QAQC Site Engineer")
        self.billing_group, _ = Group.objects.get_or_create(name="Billing Site Engineer")
        self.hse_group, _ = Group.objects.get_or_create(name="HSE Site Engineer")

        self.ho = User.objects.create_user(username="site_del_ho", password="Project@123")
        self.ho.groups.add(self.ho_group)
        self.ceo = User.objects.create_user(username="site_del_ceo", password="Project@123")
        self.ceo.groups.add(self.ceo_group)
        self.pmc = User.objects.create_user(username="site_del_pmc", password="Project@123")
        self.pmc.groups.add(self.pmc_group)
        self.admin = User.objects.create_superuser(
            username="site_del_admin", password="Project@123", email="a@example.com"
        )

        self.tl = User.objects.create_user(username="site_del_tl", password="Project@123")
        self.tl.groups.add(self.tl_group)
        self.se = User.objects.create_user(username="site_del_se", password="Project@123")
        self.se.groups.add(self.se_group)
        self.qaqc = User.objects.create_user(username="site_del_qaqc", password="Project@123")
        self.qaqc.groups.add(self.qaqc_group)
        self.billing = User.objects.create_user(
            username="site_del_billing", password="Project@123"
        )
        self.billing.groups.add(self.billing_group)
        self.hse = User.objects.create_user(username="site_del_hse", password="Project@123")
        self.hse.groups.add(self.hse_group)

        self.project = Project.objects.create(
            name="Site Delete Project",
            status="active",
            team_lead=self.tl,
        )
        self.site = Site.objects.create(
            project=self.project,
            name="Zone A",
            location="Goa",
            status="active",
        )

    def _delete(self, site_id=None):
        sid = self.site.id if site_id is None else site_id
        return self.client.delete(f"{self.URL}{sid}/")

    def test_init_list_get_unchanged(self):
        authenticate_client(self.client, username="site_del_ho", password="Project@123")
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)
        names = [row.get("name") for row in response.data]
        self.assertIn(self.project.name, names)

    def test_ho_can_delete(self):
        authenticate_client(self.client, username="site_del_ho", password="Project@123")
        response = self._delete()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["message"], "Site deleted successfully.")
        self.assertFalse(Site.objects.filter(pk=self.site.pk).exists())

    def test_ceo_can_delete(self):
        site = Site.objects.create(
            project=self.project, name="CEO Zone", location="X", status="not_started"
        )
        authenticate_client(self.client, username="site_del_ceo", password="Project@123")
        response = self._delete(site.id)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(Site.objects.filter(pk=site.pk).exists())

    def test_pmc_head_can_delete(self):
        site = Site.objects.create(
            project=self.project, name="PMC Zone", location="X", status="not_started"
        )
        authenticate_client(self.client, username="site_del_pmc", password="Project@123")
        response = self._delete(site.id)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_superuser_can_delete(self):
        site = Site.objects.create(
            project=self.project, name="Admin Zone", location="X", status="not_started"
        )
        authenticate_client(self.client, username="site_del_admin", password="Project@123")
        response = self._delete(site.id)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_tl_forbidden(self):
        authenticate_client(self.client, username="site_del_tl", password="Project@123")
        response = self._delete()
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Site.objects.filter(pk=self.site.pk).exists())

    def test_se_forbidden(self):
        authenticate_client(self.client, username="site_del_se", password="Project@123")
        self.assertEqual(self._delete().status_code, status.HTTP_403_FORBIDDEN)

    def test_qaqc_forbidden(self):
        authenticate_client(self.client, username="site_del_qaqc", password="Project@123")
        self.assertEqual(self._delete().status_code, status.HTTP_403_FORBIDDEN)

    def test_billing_forbidden(self):
        authenticate_client(self.client, username="site_del_billing", password="Project@123")
        self.assertEqual(self._delete().status_code, status.HTTP_403_FORBIDDEN)

    def test_hse_forbidden(self):
        authenticate_client(self.client, username="site_del_hse", password="Project@123")
        self.assertEqual(self._delete().status_code, status.HTTP_403_FORBIDDEN)

    def test_not_found(self):
        authenticate_client(self.client, username="site_del_ho", password="Project@123")
        response = self._delete(999999)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_dependency_blocks_delete(self):
        Task.objects.create(
            site=self.site,
            name="Task 1",
            start_date=date.today(),
            end_date=date.today() + timedelta(days=1),
        )
        DailyProgressReport.objects.create(
            site=self.site,
            project=self.project,
            submitted_by=self.ho,
            report_date=date.today(),
            work_done="Pour",
        )
        authenticate_client(self.client, username="site_del_ho", password="Project@123")
        response = self._delete()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])
        self.assertIn("dependencies", response.data)
        self.assertGreaterEqual(response.data["dependencies"].get("tasks", 0), 1)
        self.assertGreaterEqual(response.data["dependencies"].get("dpr", 0), 1)
        self.assertTrue(Site.objects.filter(pk=self.site.pk).exists())

    def test_audit_log_created(self):
        authenticate_client(self.client, username="site_del_ho", password="Project@123")
        before = UserManagementAuditLog.objects.count()
        self._delete()
        self.assertEqual(UserManagementAuditLog.objects.count(), before + 1)
        log = UserManagementAuditLog.objects.order_by("-id").first()
        self.assertEqual(log.action, UserManagementAuditLog.ACTION_DELETED)
        self.assertIn("Deleted site", log.detail)
        self.assertEqual(log.project_id, self.project.id)

    def test_cache_version_bumped(self):
        authenticate_client(self.client, username="site_del_ho", password="Project@123")
        v_before = get_list_cache_version("project_overview_v3")
        self._delete()
        v_after = get_list_cache_version("project_overview_v3")
        self.assertGreater(v_after, v_before)
