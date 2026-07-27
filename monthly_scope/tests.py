from datetime import date

from django.contrib.auth.models import Group, User
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from core.test_auth import authenticate_client
from monthly_scope.models import MonthlyScopeWork
from projects.models import Project


class MonthlyScopeNullCategoryRegressionTest(TestCase):
    def setUp(self):
        self.team_leader_group, _ = Group.objects.get_or_create(name="Team Leader")

        self.user = User.objects.create_user(
            username="ms_tl_nullcat",
            password="testpass123",
            is_active=True,
        )
        self.user.groups.add(self.team_leader_group)

        self.project = Project.objects.create(name="MS Null Category Project", status="active")
        MonthlyScopeWork.objects.create(
            project=self.project,
            month=date(2026, 1, 1),
            category=None,
            subcategory=None,
            description="legacy row with null category",
            unit="",
            planned_quantity=None,
            status="pending",
        )

        # Some legacy rows in production also have project=None.
        MonthlyScopeWork.objects.create(
            project=None,
            month=date(2026, 2, 1),
            category=None,
            subcategory=None,
            description="legacy row with null project",
            unit="",
            planned_quantity=None,
            status="pending",
        )

        self.client = APIClient()
        authenticate_client(self.client, username=self.user.username, password="testpass123")

    def test_list_does_not_500_with_null_category(self):
        response = self.client.get("/api/monthly-scope/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        # Ensure serializer returned something
        data = response.json()
        self.assertTrue(data.get("results") or data.get("count"))
