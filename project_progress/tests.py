from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework import status
from rest_framework.test import APITestCase

from .models import ProjectProgressStatus

User = get_user_model()


class ProjectProgressAPITest(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="progress_tl",
            password="testpass123",
        )
        group, _ = Group.objects.get_or_create(name="Team Leader")
        self.user.groups.add(group)

        ProjectProgressStatus.objects.create(
            project_name="Thane Project",
            progress_month=date(2026, 5, 1),
            monthly_plan=5.0,
            cumulative_plan=50.0,
            monthly_actual=4.0,
            cumulative_actual=45.0,
            created_by="test",
        )

        login = self.client.post(
            "/api/token/",
            {"username": "progress_tl", "password": "testpass123"},
            format="json",
        )
        self.assertEqual(login.status_code, status.HTTP_200_OK)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {login.data['access']}"
        )

    def test_list_with_jwt_no_role_param(self):
        """Physical progress must load with Bearer token only (no ?role=)."""
        response = self.client.get(
            "/api/project-progress/?project_name=Thane"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data), 1)
