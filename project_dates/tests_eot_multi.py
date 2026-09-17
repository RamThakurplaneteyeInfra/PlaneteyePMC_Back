"""
Tests for multi-EOT — legacy Project Dates field names + additive history.
"""

from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.test import TestCase
from rest_framework.test import APIClient

from core.test_auth import authenticate_client
from project_dates.eot_models import ProjectEOT
from project_dates.eot_services import (
    latest_completion_date,
    next_eot_number,
    sync_legacy_eot_date,
)
from project_dates.models import ProjectDates
from projects.models import Project


class ProjectEOTMultiTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="eot_admin", email="a@example.com", password="pass12345"
        )
        self.tl = User.objects.create_user(
            username="eot_tl", email="tl@example.com", password="pass12345"
        )
        Group.objects.get_or_create(name="Team Leader")[0].user_set.add(self.tl)
        self.se = User.objects.create_user(
            username="eot_se", email="se@example.com", password="pass12345"
        )
        Group.objects.get_or_create(name="Site Engineer")[0].user_set.add(self.se)

        self.project = Project.objects.create(
            name="EOT Multi Project",
            status="active",
            team_lead=self.tl,
            contract_finish=date(2026, 6, 1),
        )
        self.scl = ProjectDates.objects.create(
            project=self.project,
            date_type=ProjectDates.DATE_TYPE_SCL,
            project_start=date(2025, 1, 1),
            contract_finish=date(2026, 6, 1),
            forecast_finish=date(2026, 7, 1),
            eot_date=date(2026, 7, 1),
        )
        self.client = APIClient()
        authenticate_client(self.client, username="eot_admin", password="pass12345")

    def test_migrate_style_legacy_becomes_eot_one(self):
        eot = ProjectEOT.objects.create(
            project=self.project,
            project_dates=self.scl,
            eot_number=1,
            extension_days=30,
            original_completion_date=date(2026, 6, 1),
            revised_completion_date=date(2026, 7, 1),
            approval_date=date(2026, 6, 15),
            reason="Heavy Rain",
            status=ProjectEOT.STATUS_APPROVED,
            created_by=self.admin,
        )
        self.assertEqual(eot.eot_number, 1)
        self.assertEqual(latest_completion_date(self.project), date(2026, 7, 1))

    def test_multiple_eots_latest_completion(self):
        ProjectEOT.objects.create(
            project=self.project,
            eot_number=1,
            extension_days=30,
            original_completion_date=date(2026, 6, 1),
            revised_completion_date=date(2026, 7, 1),
            approval_date=date(2026, 6, 10),
            reason="Heavy Rain",
            status=ProjectEOT.STATUS_APPROVED,
        )
        ProjectEOT.objects.create(
            project=self.project,
            eot_number=2,
            extension_days=45,
            original_completion_date=date(2026, 7, 1),
            revised_completion_date=date(2026, 8, 15),
            approval_date=date(2026, 7, 20),
            reason="Design Change",
            status=ProjectEOT.STATUS_APPROVED,
        )
        ProjectEOT.objects.create(
            project=self.project,
            eot_number=3,
            extension_days=20,
            original_completion_date=date(2026, 8, 15),
            revised_completion_date=date(2026, 9, 4),
            reason="Utility Shifting",
            status=ProjectEOT.STATUS_PENDING,
        )
        self.assertEqual(latest_completion_date(self.project), date(2026, 8, 15))
        sync_legacy_eot_date(self.project)
        self.scl.refresh_from_db()
        self.assertEqual(self.scl.eot_date, date(2026, 8, 15))

    def test_api_create_with_legacy_payload(self):
        """Frontend-compatible create body (Project Dates field names)."""
        r1 = self.client.post(
            "/api/project-eot/",
            {
                "project_name": self.project.name,
                "date_type": "SCL",
                "contractor_id": None,
                "project_start": "2025-01-01",
                "contract_finish": "2026-06-01",
                "forecast_finish": "2026-07-01",
                "eot_date": "2026-07-01",
                "extension_days": 30,
                "reason": "Heavy Rain",
                "remarks": "Monsoon",
                "status": "approved",
                "approval_date": "2026-06-10",
            },
            format="json",
        )
        self.assertEqual(r1.status_code, 201, r1.content)
        data = r1.json()["data"]
        # Legacy fields present
        self.assertEqual(data["project_name"], self.project.name)
        self.assertEqual(data["contract_finish"], "2026-06-01")
        self.assertEqual(data["eot_date"], "2026-07-01")
        self.assertEqual(data["date_type"], "SCL")
        self.assertIn("elapsed_duration", data)
        self.assertIn("eot_duration", data)
        self.assertIn("eot_delay_days", data)
        # Additive fields
        self.assertEqual(data["eot_number"], 1)
        self.assertEqual(data["extension_days"], 30)
        self.assertEqual(data["reason"], "Heavy Rain")
        self.assertEqual(data["status"], "approved")
        # Internal names must NOT be primary contract
        self.assertNotIn("original_completion_date", data)
        self.assertNotIn("revised_completion_date", data)

        r2 = self.client.post(
            "/api/project-eot/",
            {
                "project_name": self.project.name,
                "date_type": "SCL",
                "contract_finish": "2026-07-01",
                "eot_date": "2026-08-15",
                "extension_days": 45,
                "reason": "Design Change",
                "status": "approved",
                "approval_date": "2026-07-20",
            },
            format="json",
        )
        self.assertEqual(r2.status_code, 201, r2.content)
        self.assertEqual(r2.json()["data"]["eot_date"], "2026-08-15")

        summary = self.client.get(f"/api/project-eot/project/{self.project.name}/")
        self.assertEqual(summary.status_code, 200, summary.content)
        body = summary.json()["data"]
        self.assertEqual(body["project_name"], self.project.name)
        self.assertEqual(body["eot_count"], 2)
        self.assertEqual(body["latest_completion_date"], "2026-08-15")
        self.assertEqual(body["current_eot"]["eot_date"], "2026-08-15")
        self.assertEqual(len(body["eot_history"]), 2)

    def test_create_derives_eot_date_from_extension_days(self):
        resp = self.client.post(
            "/api/project-eot/",
            {
                "project_name": self.project.name,
                "date_type": "SCL",
                "contract_finish": "2026-06-01",
                "extension_days": 10,
                "reason": "Derived",
                "status": "pending",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()["data"]["eot_date"], "2026-06-11")

    def test_duplicate_eot_number_rejected(self):
        ProjectEOT.objects.create(
            project=self.project,
            eot_number=1,
            extension_days=10,
            original_completion_date=date(2026, 6, 1),
            revised_completion_date=date(2026, 6, 11),
            approval_date=date(2026, 6, 5),
            reason="A",
            status=ProjectEOT.STATUS_APPROVED,
        )
        resp = self.client.post(
            "/api/project-eot/",
            {
                "project_name": self.project.name,
                "eot_number": 1,
                "contract_finish": "2026-06-11",
                "eot_date": "2026-06-16",
                "extension_days": 5,
                "reason": "Dup",
                "status": "pending",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_validation_uses_legacy_field_names(self):
        resp = self.client.post(
            "/api/project-eot/",
            {
                "project_name": self.project.name,
                "contract_finish": "2026-07-01",
                "eot_date": "2026-06-01",
                "extension_days": 5,
                "reason": "Bad order",
                "status": "pending",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        body = resp.json()
        errors = body.get("errors") or {}
        raw = str(body)
        self.assertIn("eot_date", raw)
        if isinstance(errors, dict):
            self.assertIn("eot_date", errors)
        elif isinstance(errors, list):
            fields = {e.get("field") for e in errors if isinstance(e, dict)}
            self.assertIn("eot_date", fields)

    def test_soft_delete(self):
        eot = ProjectEOT.objects.create(
            project=self.project,
            eot_number=1,
            extension_days=10,
            original_completion_date=date(2026, 6, 1),
            revised_completion_date=date(2026, 6, 11),
            approval_date=date(2026, 6, 5),
            reason="A",
            status=ProjectEOT.STATUS_APPROVED,
        )
        resp = self.client.delete(f"/api/project-eot/{eot.id}/")
        self.assertEqual(resp.status_code, 200, resp.content)
        eot.refresh_from_db()
        self.assertFalse(eot.is_active)
        self.assertEqual(next_eot_number(self.project), 1)

    @patch("project_dates.eot_services.invalidate_tags")
    def test_cache_invalidation_on_create(self, mock_inv):
        self.client.post(
            "/api/project-eot/",
            {
                "project_name": self.project.name,
                "contract_finish": "2026-06-01",
                "eot_date": "2026-06-13",
                "extension_days": 12,
                "reason": "Cache test",
                "status": "approved",
                "approval_date": "2026-06-12",
            },
            format="json",
        )
        self.assertTrue(mock_inv.called)

    def test_site_engineer_cannot_write(self):
        authenticate_client(self.client, username="eot_se", password="pass12345")
        resp = self.client.post(
            "/api/project-eot/",
            {
                "project_name": self.project.name,
                "contract_finish": "2026-06-01",
                "eot_date": "2026-06-06",
                "extension_days": 5,
                "reason": "No",
                "status": "pending",
            },
            format="json",
        )
        self.assertIn(resp.status_code, (403, 400))

    def test_legacy_project_dates_still_exposes_eot_date(self):
        ProjectEOT.objects.create(
            project=self.project,
            eot_number=1,
            extension_days=30,
            original_completion_date=date(2026, 6, 1),
            revised_completion_date=date(2026, 7, 1),
            approval_date=date(2026, 6, 10),
            reason="Rain",
            status=ProjectEOT.STATUS_APPROVED,
        )
        sync_legacy_eot_date(self.project)
        resp = self.client.get(f"/api/project-dates/project/{self.project.name}/")
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()["data"]
        self.assertEqual(data["scl"]["eot_date"], "2026-07-01")
        self.assertEqual(data["eot_count"], 1)
        self.assertIsNotNone(data["current_eot"])
        self.assertEqual(data["current_eot"]["eot_date"], "2026-07-01")
        self.assertEqual(data["latest_completion_date"], "2026-07-01")

    def test_status_submitted_pending_rejected_and_blank_approval_date(self):
        """UI often sends Title Case status + empty approval_date for non-approved."""
        for status_value in ("submitted", "Submitted", "pending", "Pending", "rejected", "Rejected"):
            with self.subTest(status=status_value):
                resp = self.client.post(
                    "/api/project-eot/",
                    {
                        "project_name": self.project.name,
                        "date_type": "SCL",
                        "contract_finish": "2026-06-01",
                        "eot_date": "2026-06-20",
                        "extension_days": 19,
                        "reason": f"Status {status_value}",
                        "status": status_value,
                        "approval_date": "",
                    },
                    format="multipart",
                )
                self.assertEqual(resp.status_code, 201, resp.content)
                stored = resp.json()["data"]["status"]
                self.assertEqual(stored, status_value.strip().lower())
                self.assertIsNone(resp.json()["data"].get("approval_date"))
