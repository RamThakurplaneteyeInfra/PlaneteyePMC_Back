"""Tests for project engineering team setup and RBAC."""

from datetime import date

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import TestCase
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIRequestFactory

from accounts.models import UserProfile
from accounts.rbac import (
    RBACDomain,
    get_user_assigned_project_ids,
    get_user_assigned_project_names,
    is_admin_user,
    user_can_write_domain,
    user_has_project_access,
)
from accounts.rbac_checks import enforce_project_write
from projects.models import Project


class RBACHelperTest(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name="Test Project", status="active")
        self.other = Project.objects.create(name="Other Project", status="active")

        self.tl_group, _ = Group.objects.get_or_create(name="Team Leader")
        self.se_group, _ = Group.objects.get_or_create(name="Site Engineer")
        self.bse_group, _ = Group.objects.get_or_create(name="Billing Site Engineer")
        self.qaqc_group, _ = Group.objects.get_or_create(name="QAQC Site Engineer")

        self.tl = User.objects.create_user("tl_user", password="x")
        self.se = User.objects.create_user("se_user", password="x")
        self.bse = User.objects.create_user("bse_user", password="x")
        self.qaqc = User.objects.create_user("qaqc_user", password="x")

        self.tl.groups.add(self.tl_group)
        self.se.groups.add(self.se_group)
        self.bse.groups.add(self.bse_group)
        self.qaqc.groups.add(self.qaqc_group)

        self.project.team_lead = self.tl
        self.project.site_engineer = self.se
        self.project.billing_site_engineer = self.bse
        self.project.qaqc_site_engineer = self.qaqc
        self.project.save()

    def test_assigned_user_has_project_access(self):
        self.assertTrue(user_has_project_access(self.se, self.project))
        self.assertIn(self.project.id, get_user_assigned_project_ids(self.se))

    def test_unassigned_user_denied(self):
        outsider = User.objects.create_user("outsider", password="x")
        self.assertFalse(user_has_project_access(outsider, self.project))

    def test_site_engineer_can_write_engineering_not_billing(self):
        self.assertTrue(
            user_can_write_domain(self.se, self.project, RBACDomain.ENGINEERING)
        )
        self.assertFalse(
            user_can_write_domain(self.se, self.project, RBACDomain.BILLING)
        )

    def test_billing_engineer_can_write_billing_not_qaqc(self):
        self.assertTrue(
            user_can_write_domain(self.bse, self.project, RBACDomain.BILLING)
        )
        self.assertFalse(
            user_can_write_domain(self.bse, self.project, RBACDomain.QAQC)
        )

    def test_qaqc_engineer_can_write_qaqc_not_billing(self):
        self.assertTrue(
            user_can_write_domain(self.qaqc, self.project, RBACDomain.QAQC)
        )
        self.assertFalse(
            user_can_write_domain(self.qaqc, self.project, RBACDomain.BILLING)
        )

    def test_qaqc_engineer_has_assigned_project_access(self):
        self.assertTrue(user_has_project_access(self.qaqc, self.project))

    def test_enforce_raises_for_unauthorized_write(self):
        with self.assertRaises(PermissionDenied):
            enforce_project_write(self.se, self.project, RBACDomain.BILLING)

    def test_assigned_project_lookups_are_request_cached(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as first:
            ids = get_user_assigned_project_ids(self.se)
            names = get_user_assigned_project_names(self.se)
            self.assertTrue(user_has_project_access(self.se, self.project))
        self.assertIn(self.project.id, ids)
        self.assertIn(self.project.name, names)
        self.assertGreaterEqual(len(first.captured_queries), 1)

        with CaptureQueriesContext(connection) as second:
            get_user_assigned_project_ids(self.se)
            get_user_assigned_project_names(self.se)
            user_has_project_access(self.se, self.project)
            is_admin_user(self.se)
        self.assertEqual(len(second.captured_queries), 0)

    def test_get_primary_role_does_not_n_plus_one_groups(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from accounts.models import UserProfile

        UserProfile.objects.get_or_create(user=self.se)
        profile = UserProfile.objects.select_related("user").prefetch_related(
            "user__groups"
        ).get(user=self.se)
        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(profile.get_primary_role(), "Site Engineer")
            self.assertEqual(profile.get_role_display_name(), "Site Engineer")
        self.assertEqual(len(ctx.captured_queries), 0)


class FinancialRBACAPITest(TestCase):
    """API-level checks for financial module RBAC."""

    def setUp(self):
        self.factory = APIRequestFactory()
        self.tl_group, _ = Group.objects.get_or_create(name="Team Leader")
        self.se_group, _ = Group.objects.get_or_create(name="Site Engineer")
        self.bse_group, _ = Group.objects.get_or_create(name="Billing Site Engineer")

        self.project = Project.objects.create(name="Financial RBAC Project", status="active")
        self.other = Project.objects.create(name="Other Financial Project", status="active")

        self.bse = User.objects.create_user("fin_bse", password="x")
        self.se = User.objects.create_user("fin_se", password="x")
        self.bse.groups.add(self.bse_group)
        self.se.groups.add(self.se_group)

        self.project.billing_site_engineer = self.bse
        self.project.site_engineer = self.se
        self.project.save()

    def test_bse_can_write_invoicing_domain(self):
        self.assertTrue(
            user_can_write_domain(self.bse, self.project, RBACDomain.BILLING)
        )

    def test_se_cannot_write_financial_domain(self):
        self.assertFalse(
            user_can_write_domain(self.se, self.project, RBACDomain.FINANCIAL)
        )

    def test_enforce_blocks_se_from_financial_write(self):
        with self.assertRaises(PermissionDenied):
            enforce_project_write(self.se, self.project, RBACDomain.FINANCIAL)


class HeadOfficeRBACAPITest(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name="HO Project", status="active")
        self.other = Project.objects.create(name="HO Other Project", status="inactive")
        self.ho_group, _ = Group.objects.get_or_create(name="Head Office")
        self.ho = User.objects.create_user("ho_user", password="x")
        self.ho.groups.add(self.ho_group)

    def test_head_office_is_admin_user(self):
        self.assertTrue(is_admin_user(self.ho))

    def test_head_office_has_all_project_access(self):
        self.assertTrue(user_has_project_access(self.ho, self.project))
        self.assertTrue(user_has_project_access(self.ho, self.other))
        ids = get_user_assigned_project_ids(self.ho)
        self.assertIn(self.project.id, ids)
        self.assertIn(self.other.id, ids)

    def test_head_office_can_write_all_domains(self):
        self.assertTrue(user_can_write_domain(self.ho, self.project, RBACDomain.GENERAL))
        self.assertTrue(user_can_write_domain(self.ho, self.project, RBACDomain.ENGINEERING))
        self.assertTrue(user_can_write_domain(self.ho, self.project, RBACDomain.BILLING))
        self.assertTrue(user_can_write_domain(self.ho, self.project, RBACDomain.FINANCIAL))
        self.assertTrue(user_can_write_domain(self.ho, self.project, RBACDomain.QAQC))


class SetupProjectEngineeringTeamTest(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name="Team Leader")
        Group.objects.get_or_create(name="Site Engineer")
        Group.objects.get_or_create(name="Billing Site Engineer")
        Group.objects.get_or_create(name="QAQC Site Engineer")

        self.project = Project.objects.create(
            name="KHB Multiplex, Kengeri (A-3462)",
            status="active",
        )
        self.tl = User.objects.create_user("pmc_tl1", password="old")
        self.tl.groups.add(Group.objects.get(name="Team Leader"))
        self.project.team_lead = self.tl
        self.project.save()

    def test_command_creates_and_assigns_engineers(self):
        call_command("setup_project_engineering_team", verbosity=0)

        self.project.refresh_from_db()
        self.assertEqual(self.project.site_engineer.username, "pmc_se1")
        self.assertEqual(self.project.billing_site_engineer.username, "pmc_bse1")
        self.assertEqual(self.project.qaqc_site_engineer.username, "pmc_qaqc1")
        self.assertEqual(self.project.team_lead.username, "pmc_tl1")

        se = User.objects.get(username="pmc_se1")
        self.assertTrue(se.check_password("Pmc@SE1"))
        profile = UserProfile.objects.get(user=se)
        self.assertEqual(profile.designation, "Site Engineer")
        self.assertEqual(profile.site_engineer_type, "site_engineer")

        bse = User.objects.get(username="pmc_bse1")
        self.assertTrue(bse.check_password("Pmc@BSE1"))
        self.assertTrue(bse.groups.filter(name="Billing Site Engineer").exists())

        qaqc = User.objects.get(username="pmc_qaqc1")
        self.assertTrue(qaqc.check_password("Pmc@QA1"))
        self.assertEqual(
            UserProfile.objects.get(user=qaqc).designation,
            "QA/QC Site Engineer",
        )
