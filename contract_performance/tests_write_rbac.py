"""Contract Performance write permission tests (POST/PUT/PATCH)."""

from decimal import Decimal

from django.contrib.auth.models import Group, User
from rest_framework import status
from rest_framework.test import APITestCase

from contract_performance.models.contract_performance import ContractPerformance
from core.test_auth import authenticate_client
from projects.models import Project


class ContractPerformanceWriteAPITest(APITestCase):
    def setUp(self):
        self.tl_group, _ = Group.objects.get_or_create(name="Team Leader")
        self.bse_group, _ = Group.objects.get_or_create(name="Billing Site Engineer")
        self.se_group, _ = Group.objects.get_or_create(name="Site Engineer")
        self.ho_group, _ = Group.objects.get_or_create(name="Head Office")

        self.project = Project.objects.create(name="CP Write Project", status="active")

        self.tl = User.objects.create_user("cp_tl", password="Project@123")
        self.tl.groups.add(self.tl_group)
        self.project.team_lead = self.tl
        self.project.save(update_fields=["team_lead", "updated_at"])

        self.bse = User.objects.create_user("cp_bse", password="Project@123")
        self.bse.groups.add(self.bse_group)
        self.project.billing_site_engineer = self.bse
        self.project.save(update_fields=["billing_site_engineer", "updated_at"])

        self.se = User.objects.create_user("cp_se", password="Project@123")
        self.se.groups.add(self.se_group)
        self.project.site_engineer = self.se
        self.project.site_engineers.add(self.se)
        self.project.save(update_fields=["site_engineer", "updated_at"])

        self.ho = User.objects.create_user("cp_ho", password="Project@123")
        self.ho.groups.add(self.ho_group)

        self.record = ContractPerformance.objects.create(
            projectName=self.project.name,
            billedValue=Decimal("1000.00"),
            actualReceiptValue=Decimal("800.00"),
        )

    def test_tl_can_put_and_patch(self):
        authenticate_client(self.client, "cp_tl", "Project@123")
        put_resp = self.client.put(
            f"/api/contract-performance/{self.record.id}/",
            {
                "projectName": self.project.name,
                "billedValue": "1200.00",
                "actualReceiptValue": "900.00",
            },
            format="json",
        )
        self.assertEqual(put_resp.status_code, status.HTTP_200_OK, put_resp.data)
        self.assertTrue(put_resp.data["success"])

        patch_resp = self.client.patch(
            f"/api/contract-performance/{self.record.id}/",
            {"actualReceiptValue": "950.00"},
            format="json",
        )
        self.assertEqual(patch_resp.status_code, status.HTTP_200_OK, patch_resp.data)

    def test_bse_can_post(self):
        authenticate_client(self.client, "cp_bse", "Project@123")
        other = Project.objects.create(name="CP Write Project B", status="active")
        other.billing_site_engineer = self.bse
        other.save(update_fields=["billing_site_engineer", "updated_at"])

        resp = self.client.post(
            "/api/contract-performance/",
            {
                "projectName": other.name,
                "billedValue": "500.00",
                "actualReceiptValue": "400.00",
            },
            format="json",
        )
        self.assertIn(resp.status_code, (status.HTTP_200_OK, status.HTTP_201_CREATED), resp.data)
        self.assertTrue(resp.data["success"])

    def test_ho_can_put(self):
        authenticate_client(self.client, "cp_ho", "Project@123")
        resp = self.client.put(
            f"/api/contract-performance/{self.record.id}/",
            {
                "projectName": self.project.name,
                "billedValue": "1500.00",
                "actualReceiptValue": "1000.00",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)

    def test_site_engineer_cannot_put_financial(self):
        authenticate_client(self.client, "cp_se", "Project@123")
        resp = self.client.put(
            f"/api/contract-performance/{self.record.id}/",
            {
                "projectName": self.project.name,
                "billedValue": "1200.00",
                "actualReceiptValue": "900.00",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
