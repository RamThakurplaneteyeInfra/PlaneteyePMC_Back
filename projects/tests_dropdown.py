"""Tests for project dropdown visibility fixes."""

from django.contrib.auth.models import Group, User
from rest_framework import status
from rest_framework.test import APITestCase

from core.test_auth import authenticate_client
from projects.models import Project


class ProjectDropdownAPITest(APITestCase):
    def setUp(self):
        self.ho_group, _ = Group.objects.get_or_create(name="Head Office")
        self.tl_group, _ = Group.objects.get_or_create(name="Team Leader")
        self.ho = User.objects.create_user(username="dd_ho", password="Project@123")
        self.ho.groups.add(self.ho_group)
        self.tl = User.objects.create_user(username="dd_tl", password="Project@123")
        self.tl.groups.add(self.tl_group)

        # More than PAGE_SIZE (20) so pagination would hide some on /projects/
        for i in range(25):
            Project.objects.create(name=f"DD Project {i:02d}", status="active")
        self.newest = Project.objects.create(name="ZZ Newest Dropdown Project", status="active")
        self.planning = Project.objects.create(name="Planning Only Project", status="planning")
        self.merged = Project.objects.create(name="Merged Hidden Project", status="merged")

        authenticate_client(self.client, username="dd_ho", password="Project@123")

    def test_dropdown_returns_all_without_pagination_truncation(self):
        response = self.client.get("/api/projects/dropdown/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(response.data["success"])
        names = [row["name"] for row in response.data["data"]]
        self.assertIn("ZZ Newest Dropdown Project", names)
        self.assertIn("Planning Only Project", names)
        self.assertNotIn("Merged Hidden Project", names)
        self.assertGreaterEqual(response.data["count"], 26)

    def test_dropdown_status_active_filter(self):
        response = self.client.get("/api/projects/dropdown/?status=active")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [row["name"] for row in response.data["data"]]
        self.assertIn("ZZ Newest Dropdown Project", names)
        self.assertNotIn("Planning Only Project", names)

    def test_create_defaults_to_active(self):
        response = self.client.post(
            "/api/projects/",
            {"name": "Fresh Created Project"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        project = Project.objects.get(name="Fresh Created Project")
        self.assertEqual(project.status, "active")

    def test_tl_only_sees_assigned_projects_in_dropdown(self):
        self.newest.team_lead = self.tl
        self.newest.save(update_fields=["team_lead", "updated_at"])
        authenticate_client(self.client, username="dd_tl", password="Project@123")
        response = self.client.get("/api/projects/dropdown/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [row["name"] for row in response.data["data"]]
        self.assertEqual(names, ["ZZ Newest Dropdown Project"])
