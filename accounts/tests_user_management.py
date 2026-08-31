"""Tests for HO / Admin User Management APIs (/api/users/)."""

from django.contrib.auth import authenticate
from django.contrib.auth.models import Group, User
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserManagementAuditLog
from accounts.rbac import can_manage_users
from core.test_auth import authenticate_client
from projects.models import Project


class HeadOfficeUserManagementAPITest(APITestCase):
    def setUp(self):
        self.ho_group, _ = Group.objects.get_or_create(name="Head Office")
        self.tl_group, _ = Group.objects.get_or_create(name="Team Leader")
        self.se_group, _ = Group.objects.get_or_create(name="Site Engineer")
        self.bse_group, _ = Group.objects.get_or_create(name="Billing Site Engineer")
        self.qaqc_group, _ = Group.objects.get_or_create(name="QAQC Site Engineer")
        self.hse_group, _ = Group.objects.get_or_create(name="HSE Site Engineer")

        self.ho = User.objects.create_user(username="ho_mgr", password="Project@123")
        self.ho.groups.add(self.ho_group)
        self.assertTrue(can_manage_users(self.ho))

        self.project = Project.objects.create(name="HO UM Project A", status="active")
        self.project_b = Project.objects.create(name="HO UM Project B", status="active")

        authenticate_client(self.client, username="ho_mgr", password="Project@123")

    def test_ho_can_create_team_leader(self):
        response = self.client.post(
            "/api/users/",
            {
                "full_name": "TL One",
                "username": "ho_tl_new",
                "role": "Team Leader",
                "project_ids": [self.project.id],
                "password": "SecurePass1",
                "confirm_password": "SecurePass1",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertTrue(response.data["success"])
        user = User.objects.get(username="ho_tl_new")
        self.assertTrue(user.groups.filter(name="Team Leader").exists())
        self.project.refresh_from_db()
        self.assertEqual(self.project.team_lead_id, user.id)
        self.assertTrue(
            UserManagementAuditLog.objects.filter(
                target_user=user, action=UserManagementAuditLog.ACTION_CREATED
            ).exists()
        )

    def test_ho_can_create_all_engineer_roles(self):
        cases = [
            ("Site Engineer", "ho_se_new", "site_engineer"),
            ("Billing Site Engineer", "ho_bse_new", "billing_site_engineer"),
            ("QAQC Site Engineer", "ho_qaqc_new", "qaqc_site_engineer"),
            ("HSE Site Engineer", "ho_hse_new", "hse_site_engineer"),
        ]
        for role, username, field in cases:
            with self.subTest(role=role):
                response = self.client.post(
                    "/api/users/",
                    {
                        "full_name": f"{role} User",
                        "username": username,
                        "role": role,
                        "project_ids": [self.project.id],
                        "password": "SecurePass1",
                        "confirm_password": "SecurePass1",
                    },
                    format="json",
                )
                self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
                user = User.objects.get(username=username)
                self.project.refresh_from_db()
                self.assertEqual(getattr(self.project, f"{field}_id"), user.id)

    def test_duplicate_username_friendly_error(self):
        User.objects.create_user(username="dup_user", password="x")
        response = self.client.post(
            "/api/users/",
            {
                "username": "dup_user",
                "role": "Team Leader",
                "project_ids": [self.project.id],
                "password": "SecurePass1",
                "confirm_password": "SecurePass1",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data.get("success", True))

    def test_password_mismatch(self):
        response = self.client.post(
            "/api/users/",
            {
                "username": "mm_user",
                "role": "Team Leader",
                "project_ids": [self.project.id],
                "password": "SecurePass1",
                "confirm_password": "SecurePass2",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_password_similar_to_username_allowed(self):
        username = "similar_user"
        response = self.client.post(
            "/api/users/",
            {
                "username": username,
                "full_name": "Similar User",
                "role": "Team Leader",
                "project_ids": [self.project.id],
                "password": username,
                "confirm_password": username,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        user = User.objects.get(username=username)
        self.assertTrue(user.check_password(username))

    def test_cannot_create_ho_role(self):
        response = self.client.post(
            "/api/users/",
            {
                "username": "evil_ho",
                "role": "Head Office",
                "project_ids": [self.project.id],
                "password": "SecurePass1",
                "confirm_password": "SecurePass1",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_search_filter_and_assign_projects(self):
        create = self.client.post(
            "/api/users/",
            {
                "username": "ho_se_filter",
                "full_name": "Filter SE",
                "role": "Site Engineer",
                "project_ids": [self.project.id],
                "password": "SecurePass1",
                "confirm_password": "SecurePass1",
            },
            format="json",
        )
        self.assertEqual(create.status_code, 201, create.data)
        user_id = create.data["data"]["id"]

        listed = self.client.get("/api/users/?search=Filter&role=Site%20Engineer&status=active")
        self.assertEqual(listed.status_code, 200)
        usernames = [u["username"] for u in listed.data["data"]["results"]]
        self.assertIn("ho_se_filter", usernames)

        assigned = self.client.patch(
            f"/api/users/{user_id}/assign-projects/",
            {"project_ids": [self.project.id, self.project_b.id]},
            format="json",
        )
        self.assertEqual(assigned.status_code, 200, assigned.data)
        self.assertEqual(len(assigned.data["data"]["assigned_projects"]), 2)

    def test_change_and_reset_password(self):
        create = self.client.post(
            "/api/users/",
            {
                "username": "ho_pwd_user",
                "role": "Team Leader",
                "project_ids": [self.project.id],
                "password": "SecurePass1",
                "confirm_password": "SecurePass1",
            },
            format="json",
        )
        user_id = create.data["data"]["id"]

        changed = self.client.patch(
            f"/api/users/{user_id}/change-password/",
            {"new_password": "SecurePass2", "confirm_password": "SecurePass2"},
            format="json",
        )
        self.assertEqual(changed.status_code, 200, changed.data)
        self.assertIsNotNone(authenticate(username="ho_pwd_user", password="SecurePass2"))
        self.assertIsNone(authenticate(username="ho_pwd_user", password="SecurePass1"))

        reset = self.client.patch(
            f"/api/users/{user_id}/reset-password/",
            {"password": "SecurePass3", "confirm_password": "SecurePass3"},
            format="json",
        )
        self.assertEqual(reset.status_code, 200, reset.data)
        self.assertIsNotNone(authenticate(username="ho_pwd_user", password="SecurePass3"))

    def test_activate_deactivate(self):
        create = self.client.post(
            "/api/users/",
            {
                "username": "ho_status_user",
                "role": "Billing Site Engineer",
                "project_ids": [self.project.id],
                "password": "SecurePass1",
                "confirm_password": "SecurePass1",
            },
            format="json",
        )
        user_id = create.data["data"]["id"]

        deactivated = self.client.patch(
            f"/api/users/{user_id}/status/",
            {"status": "inactive"},
            format="json",
        )
        self.assertEqual(deactivated.status_code, 200)
        user = User.objects.get(pk=user_id)
        self.assertFalse(user.is_active)

        activated = self.client.patch(
            f"/api/users/{user_id}/status/",
            {"is_active": True},
            format="json",
        )
        self.assertEqual(activated.status_code, 200)
        user.refresh_from_db()
        self.assertTrue(user.is_active)

    def test_non_ho_cannot_access(self):
        se = User.objects.create_user(username="plain_se", password="Project@123")
        se.groups.add(self.se_group)
        authenticate_client(self.client, username="plain_se", password="Project@123")
        response = self.client.get("/api/users/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
