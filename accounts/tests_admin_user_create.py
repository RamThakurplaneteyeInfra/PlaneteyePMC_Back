"""Regression tests for admin User create (profile inline) and Project team fields."""

from django.contrib.admin.sites import site
from django.contrib.auth.models import Group, User
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import UserProfile
from projects.models import Project


class AdminUserCreateProfileTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="admin_test",
            email="admin@example.com",
            password="Admin@12345",
        )
        self.client = Client()
        self.client.force_login(self.admin)
        self.se_group, _ = Group.objects.get_or_create(name="Site Engineer")
        self.tl_group, _ = Group.objects.get_or_create(name="Team Leader")

    def _profile_prefix(self, html: str) -> str:
        if 'name="profile-TOTAL_FORMS"' in html:
            return "profile"
        return "userprofile"

    def test_create_site_engineer_via_admin_does_not_500(self):
        url = reverse("admin:auth_user_add")
        get_resp = self.client.get(url)
        self.assertEqual(get_resp.status_code, 200)
        prefix = self._profile_prefix(get_resp.content.decode("utf-8", errors="ignore"))

        response = self.client.post(
            url,
            {
                "username": "admin_se_new",
                "password1": "Pmc@SE999",
                "password2": "Pmc@SE999",
                "groups": [str(self.se_group.id)],
                f"{prefix}-TOTAL_FORMS": "1",
                f"{prefix}-INITIAL_FORMS": "0",
                f"{prefix}-MIN_NUM_FORMS": "0",
                f"{prefix}-MAX_NUM_FORMS": "1",
                f"{prefix}-0-site_engineer_type": "site_engineer",
                f"{prefix}-0-phone_number": "",
                f"{prefix}-0-designation": "Site Engineer",
                f"{prefix}-0-department": "",
            },
            follow=True,
        )
        self.assertNotEqual(response.status_code, 500, msg=response.content[:800])
        self.assertTrue(User.objects.filter(username="admin_se_new").exists())
        user = User.objects.get(username="admin_se_new")
        self.assertEqual(UserProfile.objects.filter(user=user).count(), 1)
        self.assertTrue(user.groups.filter(name="Site Engineer").exists())

        # If profile type was not applied on add (edge case), change view must work
        if user.profile.site_engineer_type != "site_engineer":
            change_url = reverse("admin:auth_user_change", args=[user.pk])
            change_get = self.client.get(change_url)
            prefix = self._profile_prefix(change_get.content.decode("utf-8", errors="ignore"))
            profile = user.profile
            change_resp = self.client.post(
                change_url,
                {
                    "username": user.username,
                    "email": "",
                    "first_name": "",
                    "last_name": "",
                    "is_active": "on",
                    "date_joined_0": "2026-01-01",
                    "date_joined_1": "00:00:00",
                    "groups": [str(self.se_group.id)],
                    "initial-groups": [str(self.se_group.id)],
                    f"{prefix}-TOTAL_FORMS": "1",
                    f"{prefix}-INITIAL_FORMS": "1",
                    f"{prefix}-MIN_NUM_FORMS": "0",
                    f"{prefix}-MAX_NUM_FORMS": "1",
                    f"{prefix}-0-id": str(profile.id),
                    f"{prefix}-0-user": str(user.id),
                    f"{prefix}-0-site_engineer_type": "site_engineer",
                    f"{prefix}-0-phone_number": "",
                    f"{prefix}-0-designation": "Site Engineer",
                    f"{prefix}-0-department": "",
                },
                follow=True,
            )
            self.assertNotEqual(change_resp.status_code, 500)
            user.profile.refresh_from_db()

        self.assertEqual(user.profile.site_engineer_type, "site_engineer")

    def test_project_admin_has_team_assignment_fields(self):
        model_admin = site._registry[Project]
        fieldsets = dict(model_admin.get_fieldsets(None, None))
        self.assertIn("Team Assignment", fieldsets)
        team_fields = fieldsets["Team Assignment"]["fields"]
        for required in (
            "team_lead",
            "site_engineer",
            "billing_site_engineer",
            "qaqc_site_engineer",
            "hse_site_engineer",
            "site_engineers",
        ):
            self.assertIn(required, team_fields)


class AdminProjectAssignTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="admin_assign",
            email="admin2@example.com",
            password="Admin@12345",
        )
        self.client = Client()
        self.client.force_login(self.admin)
        tl_group, _ = Group.objects.get_or_create(name="Team Leader")
        se_group, _ = Group.objects.get_or_create(name="Site Engineer")
        self.tl = User.objects.create_user(username="tl_assign", password="Pmc@TL99")
        self.tl.groups.add(tl_group)
        self.se = User.objects.create_user(username="se_assign", password="Pmc@SE99")
        self.se.groups.add(se_group)
        UserProfile.objects.get_or_create(user=self.se)
        self.se.profile.site_engineer_type = "site_engineer"
        self.se.profile.save()

    def test_create_project_with_team_via_admin(self):
        url = reverse("admin:projects_project_add")
        response = self.client.post(
            url,
            {
                "name": "Admin Test Project",
                "client_name": "",
                "description": "",
                "location": "",
                "status": "active",
                "budget": "0",
                "original_contract_value": "0",
                "approved_vo": "0",
                "pending_vo": "0",
                "bac": "0",
                "working_hours_per_day": "8",
                "working_days_per_month": "26",
                "team_lead": str(self.tl.id),
                "site_engineer": str(self.se.id),
                "site_engineers": [str(self.se.id)],
                "coordinators": [],
            },
            follow=True,
        )
        self.assertNotEqual(response.status_code, 500)
        project = Project.objects.filter(name="Admin Test Project").first()
        self.assertIsNotNone(project)
        self.assertEqual(project.team_lead_id, self.tl.id)
        self.assertEqual(project.site_engineer_id, self.se.id)
        self.assertTrue(project.site_engineers.filter(id=self.se.id).exists())
