"""Tests for budget performance API and RBAC."""

from django.contrib.auth.models import Group, User
from rest_framework import status
from rest_framework.test import APITestCase

from core.test_auth import authenticate_client
from projects.models import Project

from .models import BudgetCostPerformance


class BudgetPerformanceRBACAPITest(APITestCase):
    def setUp(self):
        self.canonical_name = "KHB Multiplex, Kengeri (A-3462)"
        self.canonical_project = Project.objects.create(
            name=self.canonical_name,
            status="active",
        )
        self.duplicate_project = Project.objects.create(
            name="Khb Multiplex, Kengeri (A-3462)",
            status="active",
        )

        self.bse_group, _ = Group.objects.get_or_create(name="Billing Site Engineer")
        self.bse = User.objects.create_user("pmc_bse1", password="testpass123")
        self.bse.groups.add(self.bse_group)
        self.canonical_project.billing_site_engineer = self.bse
        self.canonical_project.save()

        self.record = BudgetCostPerformance.objects.create(
            project_name="Khb Multiplex, Kengeri (A-3462)",
            project=self.duplicate_project,
            bac="1000000.0000",
            bcwp="500000.0000",
            acwp="400000.0000",
            cpi="1.250000",
            eac="800000.0000",
            etg="400000.0000",
            vac="200000.0000",
            cv="100000.0000",
        )

        authenticate_client(self.client, username="pmc_bse1", password="testpass123")

    def test_billing_site_engineer_can_put_budget_performance_with_mismatched_fk(self):
        response = self.client.put(
            f"/api/budget-performance/{self.record.id}/",
            {
                "project_name": self.canonical_name,
                "budget_at_completion": "1100000",
                "earned_value": "550000",
                "actual_cost": "420000",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.record.refresh_from_db()
        self.assertEqual(self.record.project_id, self.canonical_project.id)
        self.assertEqual(self.record.project_name, self.canonical_name)

    def test_billing_site_engineer_can_patch_budget_performance(self):
        response = self.client.patch(
            f"/api/budget-performance/{self.record.id}/",
            {"earned_value": "560000"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
