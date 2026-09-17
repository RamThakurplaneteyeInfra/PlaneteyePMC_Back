"""Security regression: cashflow list must always apply project RBAC."""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserProfile
from cashflow.models import CashFlow
from projects.models import Project

User = get_user_model()


class CashflowListRbacTest(APITestCase):
    def setUp(self):
        self.project_a = Project.objects.create(name="Cashflow Project A", status="active")
        self.project_b = Project.objects.create(name="Cashflow Project B", status="active")

        CashFlow.objects.create(
            project_name=self.project_a.name,
            month_year="Jan-2026",
            cash_in_monthly_plan=100,
            cash_in_monthly_actual=90,
            cash_out_monthly_plan=50,
            cash_out_monthly_actual=40,
            actual_cost_monthly=30,
        )
        CashFlow.objects.create(
            project_name=self.project_b.name,
            month_year="Jan-2026",
            cash_in_monthly_plan=200,
            cash_in_monthly_actual=180,
            cash_out_monthly_plan=80,
            cash_out_monthly_actual=70,
            actual_cost_monthly=60,
        )

        tl_group, _ = Group.objects.get_or_create(name="Team Leader")
        self.tl = User.objects.create_user(username="cf_tl", password="testpass123")
        self.tl.groups.add(tl_group)
        UserProfile.objects.get_or_create(user=self.tl)
        self.project_a.team_lead = self.tl
        self.project_a.save(update_fields=["team_lead"])

        login = self.client.post(
            "/api/token/",
            {"username": "cf_tl", "password": "testpass123"},
            format="json",
        )
        self.assertEqual(login.status_code, status.HTTP_200_OK)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

    def _list_project_names(self):
        response = self.client.get("/api/cashflow/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        if isinstance(data, dict) and "results" in data:
            rows = data["results"]
        else:
            rows = data
        return {row["project_name"] for row in rows}

    def test_list_only_returns_assigned_projects(self):
        names = self._list_project_names()
        self.assertIn(self.project_a.name, names)
        self.assertNotIn(self.project_b.name, names)
