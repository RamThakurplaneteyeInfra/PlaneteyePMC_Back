"""Tests for Planned vs Actual — SCL + multiple contractors."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Notification
from contractors.models import Contractor
from core.test_auth import authenticate_client
from planned_earned_value.controllers.metrics import contractor_summary_from_records
from planned_earned_value.models import PlannedEarnedValue
from projects.models import Project
from services.billing_update_notifications import (
    BillingAction,
    BillingModule,
    notify_team_leader,
)


class PlannedVsActualMetricsTest(TestCase):
    def test_contractor_summary_from_records(self):
        project = Project.objects.create(name="Thane Project", status="active")
        c1 = Contractor.objects.create(project=project, contractor_name="ABC Infra")
        c2 = Contractor.objects.create(project=project, contractor_name="XYZ Construction")
        r1 = PlannedEarnedValue(
            project=project,
            project_name=project.name,
            planned_type="CONTRACTOR",
            contractor=c1,
            contractor_name=c1.contractor_name,
            month=7,
            year=2026,
            planned_value=Decimal("100"),
            actual_value=Decimal("90"),
            collection=Decimal("80"),
            reason_for_difference="delay",
        )
        r1.recalculate()
        r2 = PlannedEarnedValue(
            project=project,
            project_name=project.name,
            planned_type="CONTRACTOR",
            contractor=c2,
            contractor_name=c2.contractor_name,
            month=7,
            year=2026,
            planned_value=Decimal("100"),
            actual_value=Decimal("80"),
            collection=Decimal("70"),
            reason_for_difference="delay",
        )
        r2.recalculate()
        summary = contractor_summary_from_records([r1, r2])
        self.assertEqual(summary["planned_value"], Decimal("200"))
        self.assertEqual(summary["actual_value"], Decimal("170"))
        self.assertEqual(summary["difference"], Decimal("30.00"))
        self.assertEqual(summary["achievement_percentage"], Decimal("85.00"))


class PlannedVsActualAPITest(APITestCase):
    URL = "/api/planned-vs-actual/"

    def setUp(self):
        self.project = Project.objects.create(name="Thane Project", status="active")
        self.other = Project.objects.create(name="Pune Project", status="active")
        self.c1 = Contractor.objects.create(
            project=self.project, contractor_name="ABC Infra"
        )
        self.c2 = Contractor.objects.create(
            project=self.project, contractor_name="XYZ Construction"
        )

        self.bse_group, _ = Group.objects.get_or_create(name="Billing Site Engineer")
        self.tl_group, _ = Group.objects.get_or_create(name="Team Leader")
        self.bse = User.objects.create_user("pev_bse2", password="testpass123")
        self.bse.groups.add(self.bse_group)
        self.tl = User.objects.create_user("pev_tl2", password="testpass123")
        self.tl.groups.add(self.tl_group)

        self.project.billing_site_engineer = self.bse
        self.project.team_lead = self.tl
        self.project.save()
        self.other.billing_site_engineer = self.bse
        self.other.team_lead = self.tl
        self.other.save()

        authenticate_client(self.client, username="pev_bse2", password="testpass123")

    def _scl(self, **overrides):
        data = {
            "project_name": self.project.name,
            "planned_type": "SCL",
            "month": 7,
            "year": 2026,
            "planned_value": "15000000",
            "actual_value": "14500000",
            "collection": "14000000",
            "reason_for_difference": "Rain delay",
        }
        data.update(overrides)
        return data

    def _contractor(self, contractor_id, **overrides):
        data = {
            "project_name": self.project.name,
            "planned_type": "CONTRACTOR",
            "contractor_id": contractor_id,
            "month": 7,
            "year": 2026,
            "planned_value": "5000000",
            "actual_value": "4700000",
            "collection": "4500000",
            "reason_for_difference": "Delayed material supply",
        }
        data.update(overrides)
        return data

    def test_scl_upsert(self):
        create = self.client.post(self.URL, self._scl(), format="json")
        self.assertEqual(create.status_code, status.HTTP_201_CREATED)
        self.assertEqual(create.data["data"]["planned_type"], "SCL")
        self.assertIsNone(create.data["data"]["contractor"])

        update = self.client.post(
            self.URL,
            self._scl(actual_value="15000000", reason_for_difference=""),
            format="json",
        )
        self.assertEqual(update.status_code, status.HTTP_200_OK)
        self.assertEqual(
            PlannedEarnedValue.objects.filter(planned_type="SCL").count(), 1
        )

    def test_contractor_upsert(self):
        create = self.client.post(self.URL, self._contractor(self.c1.id), format="json")
        self.assertEqual(create.status_code, status.HTTP_201_CREATED)
        self.assertEqual(create.data["data"]["planned_type"], "CONTRACTOR")
        self.assertEqual(create.data["data"]["contractor"]["id"], self.c1.id)

        update = self.client.post(
            self.URL,
            self._contractor(self.c1.id, actual_value="5000000", reason_for_difference=""),
            format="json",
        )
        self.assertEqual(update.status_code, status.HTTP_200_OK)
        self.assertEqual(
            PlannedEarnedValue.objects.filter(
                planned_type="CONTRACTOR", contractor=self.c1
            ).count(),
            1,
        )

    def test_multiple_contractors(self):
        self.client.post(self.URL, self._contractor(self.c1.id), format="json")
        self.client.post(
            self.URL,
            self._contractor(self.c2.id, planned_value="3000000", actual_value="2800000"),
            format="json",
        )
        self.assertEqual(
            PlannedEarnedValue.objects.filter(planned_type="CONTRACTOR").count(), 2
        )

    def test_project_wise_retrieval_and_summary(self):
        self.client.post(self.URL, self._scl(), format="json")
        self.client.post(self.URL, self._contractor(self.c1.id), format="json")
        self.client.post(
            self.URL,
            self._contractor(
                self.c2.id,
                planned_value="3000000",
                actual_value="2800000",
                collection="2700000",
            ),
            format="json",
        )
        response = self.client.get(
            f"{self.URL}project/Thane%20Project/?month=7&year=2026"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["data"]
        self.assertIsNotNone(data["scl"])
        self.assertEqual(len(data["contractors"]), 2)
        self.assertEqual(data["contractor_summary"]["planned_value"], 8000000.0)
        self.assertEqual(data["contractor_summary"]["actual_value"], 7500000.0)

    def test_contractor_retrieval_requires_id_when_multiple(self):
        self.client.post(self.URL, self._contractor(self.c1.id), format="json")
        self.client.post(self.URL, self._contractor(self.c2.id), format="json")
        missing = self.client.get(
            f"{self.URL}project/Thane%20Project/type/CONTRACTOR/?month=7&year=2026"
        )
        self.assertEqual(missing.status_code, status.HTTP_400_BAD_REQUEST)

        ok = self.client.get(
            f"{self.URL}project/Thane%20Project/type/CONTRACTOR/"
            f"?contractor_id={self.c1.id}&month=7&year=2026"
        )
        self.assertEqual(ok.status_code, status.HTTP_200_OK)
        self.assertEqual(ok.data["data"]["contractor"]["id"], self.c1.id)

    def test_contractor_by_type_returns_null_when_missing(self):
        response = self.client.get(
            f"{self.URL}project/Thane%20Project/type/CONTRACTOR/"
            f"?contractor_id={self.c1.id}&month=7&year=2026"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertIsNone(response.data["data"])

    def test_dashboard(self):
        self.client.post(self.URL, self._scl(), format="json")
        response = self.client.get(f"{self.URL}dashboard/?month=7&year=2026")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        summary = response.data["data"]["summary"]
        self.assertEqual(summary["updated_projects"], 1)
        self.assertIn("projects_on_track", summary)
        self.assertIn("projects_minor_variance", summary)
        self.assertIn("projects_major_variance", summary)

    def test_trend_api(self):
        self.client.post(self.URL, self._scl(), format="json")
        self.client.post(self.URL, self._contractor(self.c1.id), format="json")
        response = self.client.get(
            f"{self.URL}project/Thane%20Project/trend/?year=2026"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        months = response.data["data"]["months"]
        self.assertEqual(len(months), 12)
        july = months[6]
        self.assertIsNotNone(july["scl"])
        self.assertEqual(len(july["contractors"]), 1)

    def test_pending_projects(self):
        self.client.post(self.URL, self._scl(), format="json")
        # Thane still pending because contractors missing; Pune missing SCL
        response = self.client.get(f"{self.URL}pending/?month=7&year=2026")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        pending = response.data["data"]["pending_projects"]
        self.assertIn("Thane Project", pending)
        self.assertIn("Pune Project", pending)

        self.client.post(self.URL, self._contractor(self.c1.id), format="json")
        self.client.post(self.URL, self._contractor(self.c2.id), format="json")
        response2 = self.client.get(f"{self.URL}pending/?month=7&year=2026")
        self.assertNotIn("Thane Project", response2.data["data"]["pending_projects"])

    def test_reason_validation(self):
        response = self.client.post(
            self.URL,
            self._scl(reason_for_difference=""),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_export_csv(self):
        self.client.post(self.URL, self._scl(), format="json")
        self.client.post(self.URL, self._contractor(self.c1.id), format="json")
        response = self.client.get(f"{self.URL}?export=csv&month=7&year=2026")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(b"Type", response.content)
        self.assertIn(b"SCL", response.content)
        self.assertIn(b"ABC Infra", response.content)

    @patch(
        "planned_earned_value.controllers.planned_earned_value_controller."
        "schedule_billing_update_notification_for_instance"
    )
    def test_notifications(self, mock_schedule):
        response = self.client.post(self.URL, self._scl(), format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        mock_schedule.assert_called_once()
        self.assertEqual(mock_schedule.call_args[0][2], "Planned vs Actual")

        notification = notify_team_leader(
            self.project,
            self.bse,
            BillingModule.PLANNED_VS_ACTUAL,
            BillingAction.CREATE,
        )
        self.assertIsNotNone(notification)
        self.assertTrue(
            Notification.objects.filter(
                module_name="Planned vs Actual",
                user=self.tl,
            ).exists()
        )

    def test_rbac_blocks_unassigned_user(self):
        outsider = User.objects.create_user("pev_out2", password="testpass123")
        outsider.groups.add(self.bse_group)
        authenticate_client(self.client, username="pev_out2", password="testpass123")
        response = self.client.post(self.URL, self._scl(), format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_legacy_url_alias(self):
        response = self.client.post(
            "/api/planned-earned-value/",
            self._scl(),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
