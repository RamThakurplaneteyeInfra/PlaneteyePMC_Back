from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserProfile

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
        UserProfile.objects.get_or_create(user=self.user)

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

    def test_client_supplied_role_cannot_elevate_access(self):
        """Site Engineer cannot spoof PMC Head via query/header/body."""
        se = User.objects.create_user(username="progress_se", password="testpass123")
        se_group, _ = Group.objects.get_or_create(name="Site Engineer")
        se.groups.add(se_group)
        UserProfile.objects.get_or_create(user=se)

        login = self.client.post(
            "/api/token/",
            {"username": "progress_se", "password": "testpass123"},
            format="json",
        )
        self.assertEqual(login.status_code, status.HTTP_200_OK)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {login.data['access']}"
        )

        forbidden = self.client.get(
            "/api/project-progress/?role=PMC%20Head",
            HTTP_X_ROLE="PMC Head",
        )
        self.assertEqual(forbidden.status_code, status.HTTP_403_FORBIDDEN)
