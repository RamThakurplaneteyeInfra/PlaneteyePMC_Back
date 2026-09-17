"""Tests for monthly Health & Safety statistics on HealthSafetyRecord."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserProfile
from health_safety.models import HealthSafetyRecord
from projects.models import Project

User = get_user_model()


class MonthlyHealthSafetyStatsTests(APITestCase):
    def setUp(self):
        self.project = Project.objects.create(name="HSE Stats Project", status="active")

        self.hse = User.objects.create_user(username="hse_stats", password="testpass123")
        hse_group, _ = Group.objects.get_or_create(name="HSE Site Engineer")
        self.hse.groups.add(hse_group)
        UserProfile.objects.get_or_create(user=self.hse)
        self.project.hse_site_engineer = self.hse
        self.project.save(update_fields=["hse_site_engineer", "updated_at"])

        self.other = User.objects.create_user(username="hse_other", password="testpass123")
        self.other.groups.add(hse_group)
        UserProfile.objects.get_or_create(user=self.other)

        login = self.client.post(
            "/api/token/",
            {"username": "hse_stats", "password": "testpass123"},
            format="json",
        )
        self.assertEqual(login.status_code, status.HTTP_200_OK)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

    def test_auto_calculations_on_create(self):
        payload = {
            "project_name": self.project.name,
            "month": 6,
            "year": 2026,
            "average_daily_manpower": "50.00",
            "working_days": 26,
            "near_miss": 2,
            "reportable_accident_lti": 1,
            "dangerous_occurrences": 0,
            "first_aid_cases": 3,
            "medical_treatment_cases": 1,
            "utility_damage": 1,
            "loss_of_manhours": "16.00",
            "internal_training_count": 2,
            "internal_training_hours": "8.00",
            "external_training_count": 1,
            "external_training_hours": "4.00",
            "mock_drills": 1,
            "medical_checkup_workers": 40,
            "medical_checkup_staff": 5,
        }
        response = self.client.post("/api/health-safety/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        data = response.data["data"]
        self.assertEqual(Decimal(str(data["man_days_worked"])), Decimal("1300.00"))
        self.assertEqual(Decimal(str(data["man_hours_worked"])), Decimal("10400.00"))
        self.assertEqual(Decimal(str(data["total_manhours"])), Decimal("10400.00"))
        self.assertEqual(data["medical_checkup_total"], 45)
        self.assertEqual(data["near_miss"], 2)
        self.assertEqual(data["reportable_accident_lti"], 1)

    def test_legacy_fields_still_accepted(self):
        """Backward compatible create with original fields only."""
        payload = {
            "project_name": self.project.name,
            "month": 7,
            "year": 2026,
            "fatalities": 0,
            "significant": 0,
            "major": 0,
            "minor": 1,
            "near_miss": 2,
            "total_manhours": "1000.00",
            "loss_of_manhours": "8.00",
        }
        response = self.client.post("/api/health-safety/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        data = response.data["data"]
        self.assertEqual(Decimal(str(data["total_manhours"])), Decimal("1000.00"))
        self.assertEqual(data["near_miss"], 2)
        self.assertIn("average_daily_manpower", data)
        self.assertIn("mock_drills", data)

    def test_update_recalculates(self):
        record = HealthSafetyRecord.objects.create(
            project_name=self.project.name,
            month=8,
            year=2026,
            average_daily_manpower=Decimal("10"),
            working_days=20,
            medical_checkup_workers=10,
            medical_checkup_staff=2,
        )
        self.assertEqual(record.man_days_worked, Decimal("200.00"))
        self.assertEqual(record.medical_checkup_total, 12)

        response = self.client.patch(
            f"/api/health-safety/{record.id}/",
            {
                "average_daily_manpower": "20.00",
                "working_days": 25,
                "medical_checkup_workers": 15,
                "medical_checkup_staff": 5,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        data = response.data["data"]
        self.assertEqual(Decimal(str(data["man_days_worked"])), Decimal("500.00"))
        self.assertEqual(Decimal(str(data["man_hours_worked"])), Decimal("4000.00"))
        self.assertEqual(data["medical_checkup_total"], 20)

    def test_working_days_required_when_manpower_set(self):
        response = self.client.post(
            "/api/health-safety/",
            {
                "project_name": self.project.name,
                "month": 9,
                "year": 2026,
                "average_daily_manpower": "10.00",
                "working_days": 0,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_negative_values_rejected(self):
        response = self.client.post(
            "/api/health-safety/",
            {
                "project_name": self.project.name,
                "month": 10,
                "year": 2026,
                "near_miss": -1,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rbac_other_hse_cannot_access_unassigned_project(self):
        HealthSafetyRecord.objects.create(
            project_name=self.project.name,
            month=11,
            year=2026,
            near_miss=1,
        )
        login = self.client.post(
            "/api/token/",
            {"username": "hse_other", "password": "testpass123"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        response = self.client.get(
            f"/api/health-safety/?project_name={self.project.name}"
        )
        # Unassigned HSE may get empty list (200) or forbidden (403) depending on
        # project-write/list policy — either means no data leak.
        self.assertIn(
            response.status_code,
            (status.HTTP_200_OK, status.HTTP_403_FORBIDDEN),
            response.data,
        )
        if response.status_code == status.HTTP_200_OK:
            payload = response.data.get("data", response.data)
            if isinstance(payload, dict) and "results" in payload:
                self.assertEqual(len(payload["results"]), 0)
            else:
                self.assertEqual(len(payload), 0)

    def test_dashboard_includes_new_fields(self):
        import datetime

        today = datetime.date.today()
        HealthSafetyRecord.objects.create(
            project_name=self.project.name,
            month=today.month,
            year=today.year,
            average_daily_manpower=Decimal("40"),
            working_days=22,
            near_miss=3,
            reportable_accident_lti=1,
            utility_damage=2,
            mock_drills=1,
            medical_checkup_workers=30,
            medical_checkup_staff=4,
            loss_of_manhours=Decimal("8"),
        )
        response = self.client.get(
            f"/api/health-safety/project/{self.project.name}/dashboard/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        current = response.data["data"]["current_month"]
        self.assertIsNotNone(current)
        self.assertEqual(current["near_miss"], 3)
        self.assertEqual(current["reportable_accident_lti"], 1)
        self.assertEqual(current["utility_damage"], 2)
        self.assertEqual(current["mock_drills"], 1)
        self.assertEqual(current["medical_checkup_total"], 34)
        self.assertEqual(Decimal(str(current["man_hours_worked"])), Decimal("7040.00"))
        ytd = response.data["data"]["year_to_date"]
        self.assertIn("man_hours_worked", ytd)
        self.assertIn("medical_checkup_total", ytd)
