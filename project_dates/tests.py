"""Tests for Project Dates and multi-entry BG Status."""

from datetime import date
from io import StringIO

from django.core.management import call_command
from django.test import TestCase, TransactionTestCase
from rest_framework import status
from rest_framework.test import APITestCase

from core.test_auth import authenticate_client
from projects.models import Project

from .bg_serializers import BGStatusSerializer
from .bg_status import (
    BG_STATUS_NOT_UPDATED,
    BG_STATUS_UPDATED,
    BG_STATUS_YET_TO_UPDATE,
    EMPTY_BG_PAYLOAD,
    bg_status_payload,
    calculate_bg_status,
    calculate_bg_summary,
)
from .models import BGStatus, ProjectBGStatus, ProjectDates


class BGStatusHelperTest(TestCase):
    def test_updated_before_due_date(self):
        self.assertEqual(
            calculate_bg_status(
                date(2026, 6, 17),
                date(2026, 6, 15),
                today=date(2026, 6, 20),
            ),
            BG_STATUS_UPDATED,
        )

    def test_updated_on_due_date(self):
        self.assertEqual(
            calculate_bg_status(
                date(2026, 6, 17),
                date(2026, 6, 17),
                today=date(2026, 6, 17),
            ),
            BG_STATUS_UPDATED,
        )

    def test_late_update_is_not_updated(self):
        self.assertEqual(
            calculate_bg_status(
                date(2026, 6, 15),
                date(2026, 6, 16),
                today=date(2026, 6, 20),
            ),
            BG_STATUS_NOT_UPDATED,
        )

    def test_due_date_not_reached_without_update(self):
        self.assertEqual(
            calculate_bg_status(
                date(2026, 6, 17),
                None,
                today=date(2026, 6, 10),
            ),
            BG_STATUS_YET_TO_UPDATE,
        )

    def test_due_date_passed_without_update(self):
        self.assertEqual(
            calculate_bg_status(
                date(2026, 6, 17),
                None,
                today=date(2026, 6, 20),
            ),
            BG_STATUS_NOT_UPDATED,
        )

    def test_due_date_today_without_update(self):
        self.assertEqual(
            calculate_bg_status(
                date(2026, 6, 17),
                None,
                today=date(2026, 6, 17),
            ),
            BG_STATUS_NOT_UPDATED,
        )

    def test_null_due_date(self):
        self.assertEqual(
            calculate_bg_status(None, None),
            BG_STATUS_YET_TO_UPDATE,
        )

    def test_compliance_summary_mixed_statuses(self):
        entries = [
            type("E", (), {"due_date": date(2026, 6, 15), "updated_date": date(2026, 6, 14)})(),
            type("E", (), {"due_date": date(2026, 6, 20), "updated_date": None})(),
            type("E", (), {"due_date": date(2026, 6, 10), "updated_date": None})(),
        ]
        summary = calculate_bg_summary(entries, today=date(2026, 6, 16))
        self.assertEqual(summary["total_bg"], 3)
        self.assertEqual(summary["updated"], 1)
        self.assertEqual(summary["yet_to_update"], 1)
        self.assertEqual(summary["not_updated"], 1)
        self.assertEqual(summary["compliance_percentage"], 33.33)

    def test_empty_compliance_summary(self):
        self.assertEqual(
            calculate_bg_summary([]),
            EMPTY_BG_PAYLOAD["bg_summary"],
        )


class BGStatusSerializerTest(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name="Thane Project")
        self.contractor_dates = ProjectDates.objects.create(
            project=self.project,
            date_type=ProjectDates.DATE_TYPE_CONTRACTOR,
            project_start=date(2024, 6, 1),
            contract_finish=date(2026, 6, 1),
            forecast_finish=date(2026, 9, 1),
            eot_date=date(2026, 12, 1),
        )
        self.entry = BGStatus.objects.create(
            project_date=self.contractor_dates,
            bg_type=BGStatus.BG_TYPE_CONTRACTOR,
            bg_name="Performance BG",
            due_date=date(2026, 6, 17),
            updated_date=date(2026, 6, 15),
        )

    def test_serializer_calculates_status(self):
        data = BGStatusSerializer(self.entry).data
        self.assertEqual(data["status"], BG_STATUS_UPDATED)
        self.assertEqual(data["bg_name"], "Performance BG")


class LegacyBGMigrationTest(TransactionTestCase):
    def test_migrates_legacy_project_bg_status_into_bgstatus_rows(self):
        call_command("migrate", "project_dates", "0003", verbosity=0)

        project = Project.objects.create(name="Legacy Project")
        ProjectDates.objects.create(
            project=project,
            date_type=ProjectDates.DATE_TYPE_CONTRACTOR,
            project_start=date(2024, 1, 1),
            contract_finish=date(2026, 1, 1),
            forecast_finish=date(2026, 3, 1),
            eot_date=date(2026, 6, 1),
        )
        ProjectDates.objects.create(
            project=project,
            date_type=ProjectDates.DATE_TYPE_SCL,
            project_start=date(2024, 1, 1),
            contract_finish=date(2026, 1, 1),
            forecast_finish=date(2026, 3, 1),
            eot_date=date(2026, 6, 1),
        )
        ProjectBGStatus.objects.create(
            project=project,
            contractor_bg_due_date=date(2026, 6, 17),
            contractor_bg_updated_date=date(2026, 6, 15),
            scl_bg_due_date=date(2026, 6, 18),
            scl_bg_updated_date=None,
        )

        out = StringIO()
        call_command("migrate", "project_dates", "0004", verbosity=0, stdout=out)

        payload = bg_status_payload(project, today=date(2026, 6, 16))
        self.assertEqual(len(payload["contractor_bg"]), 1)
        self.assertEqual(len(payload["scl_bg"]), 1)
        self.assertEqual(payload["contractor_bg"][0]["status"], BG_STATUS_UPDATED)
        self.assertEqual(payload["scl_bg"][0]["status"], BG_STATUS_YET_TO_UPDATE)


class ProjectDatesBGStatusAPITest(APITestCase):
    LIST_URL = "/api/project-dates/"
    BG_URL = "/api/project-dates/project/Thane%20Project/bg-status/"
    BY_PROJECT_URL = "/api/project-dates/project/Thane%20Project/"

    def setUp(self):
        self.project = Project.objects.create(name="Thane Project")
        authenticate_client(self.client)
        ProjectDates.objects.filter(project=self.project).delete()
        BGStatus.objects.filter(project_date__project=self.project).delete()
        ProjectBGStatus.objects.filter(project=self.project).delete()

    def _create_schedule_records(self):
        scl = ProjectDates.objects.create(
            project=self.project,
            date_type=ProjectDates.DATE_TYPE_SCL,
            project_start=date(2024, 6, 1),
            contract_finish=date(2026, 6, 1),
            forecast_finish=date(2026, 9, 1),
            eot_date=date(2026, 12, 1),
        )
        contractor = ProjectDates.objects.create(
            project=self.project,
            date_type=ProjectDates.DATE_TYPE_CONTRACTOR,
            project_start=date(2024, 6, 1),
            contract_finish=date(2026, 6, 1),
            forecast_finish=date(2026, 9, 1),
            eot_date=date(2026, 12, 1),
        )
        return scl, contractor

    def _empty_bg_payload(self):
        return dict(EMPTY_BG_PAYLOAD)

    def test_get_bg_status_empty(self):
        response = self.client.get(self.BG_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["data"], self._empty_bg_payload())

    def test_post_creates_contractor_bg_entry(self):
        self._create_schedule_records()
        response = self.client.post(
            self.BG_URL,
            {
                "bg_type": "CONTRACTOR",
                "bg_name": "Performance BG",
                "due_date": "2026-06-15",
                "updated_date": "2026-06-14",
                "remarks": "Updated successfully",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["data"]["bg_name"], "Performance BG")
        self.assertEqual(response.data["data"]["status"], BG_STATUS_UPDATED)

    def test_post_creates_multiple_contractor_bgs(self):
        self._create_schedule_records()
        self.client.post(
            self.BG_URL,
            {
                "bg_type": "CONTRACTOR",
                "bg_name": "Performance BG",
                "due_date": "2026-06-15",
                "updated_date": "2026-06-14",
            },
            format="json",
        )
        response = self.client.post(
            self.BG_URL,
            {
                "bg_type": "CONTRACTOR",
                "bg_name": "Security BG",
                "due_date": "2026-06-20",
                "updated_date": None,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        get_response = self.client.get(self.BG_URL)
        self.assertEqual(len(get_response.data["data"]["contractor_bg"]), 2)
        self.assertEqual(get_response.data["data"]["contractor_bg"][1]["bg_name"], "Security BG")

    def test_post_creates_multiple_scl_bgs(self):
        self._create_schedule_records()
        self.client.post(
            self.BG_URL,
            {
                "bg_type": "SCL",
                "bg_name": "Advance BG",
                "due_date": "2026-06-18",
            },
            format="json",
        )
        self.client.post(
            self.BG_URL,
            {
                "bg_type": "SCL",
                "bg_name": "Retention BG",
                "due_date": "2026-07-01",
            },
            format="json",
        )
        get_response = self.client.get(self.BG_URL)
        self.assertEqual(len(get_response.data["data"]["scl_bg"]), 2)

    def test_post_requires_matching_project_dates_record(self):
        response = self.client.post(
            self.BG_URL,
            {
                "bg_type": "CONTRACTOR",
                "bg_name": "Performance BG",
                "due_date": "2026-06-15",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("bg_type", response.data["errors"])

    def test_patch_updates_bg_entry(self):
        self._create_schedule_records()
        create_response = self.client.post(
            self.BG_URL,
            {
                "bg_type": "CONTRACTOR",
                "bg_name": "Performance BG",
                "due_date": "2026-06-15",
            },
            format="json",
        )
        bg_id = create_response.data["data"]["id"]
        response = self.client.patch(
            f"/api/project-dates/bg-status/{bg_id}/",
            {"updated_date": "2026-06-16", "remarks": "Renewed"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["updated_date"], "2026-06-16")
        self.assertEqual(response.data["data"]["remarks"], "Renewed")

    def test_delete_bg_entry(self):
        self._create_schedule_records()
        create_response = self.client.post(
            self.BG_URL,
            {
                "bg_type": "SCL",
                "bg_name": "Advance BG",
                "due_date": "2026-06-18",
            },
            format="json",
        )
        bg_id = create_response.data["data"]["id"]
        response = self.client.delete(f"/api/project-dates/bg-status/{bg_id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(BGStatus.objects.filter(pk=bg_id).count(), 0)

    def test_get_includes_summary_with_mixed_statuses(self):
        self._create_schedule_records()
        self.client.post(
            self.BG_URL,
            {
                "bg_type": "CONTRACTOR",
                "bg_name": "Performance BG",
                "due_date": "2026-06-15",
                "updated_date": "2026-06-14",
            },
            format="json",
        )
        self.client.post(
            self.BG_URL,
            {
                "bg_type": "CONTRACTOR",
                "bg_name": "Security BG",
                "due_date": "2026-12-31",
            },
            format="json",
        )
        self.client.post(
            self.BG_URL,
            {
                "bg_type": "SCL",
                "bg_name": "Advance BG",
                "due_date": "2020-01-01",
            },
            format="json",
        )

        response = self.client.get(self.BG_URL)
        summary = response.data["data"]["bg_summary"]
        self.assertEqual(summary["total_bg"], 3)
        self.assertEqual(summary["updated"], 1)
        self.assertGreaterEqual(summary["yet_to_update"], 1)
        self.assertGreaterEqual(summary["not_updated"], 1)

    def test_list_includes_bg_status(self):
        self._create_schedule_records()
        self.client.post(
            self.BG_URL,
            {
                "bg_type": "SCL",
                "bg_name": "Advance BG",
                "due_date": "2026-06-17",
                "updated_date": "2026-06-15",
            },
            format="json",
        )
        response = self.client.get(self.LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        records = response.data["data"]["results"]
        self.assertEqual(len(records), 2)
        bg = records[0]["bg_status"]
        self.assertEqual(len(bg["scl_bg"]), 1)
        self.assertEqual(bg["scl_bg"][0]["status"], BG_STATUS_UPDATED)

    def test_by_project_includes_bg_lists_and_summary(self):
        self._create_schedule_records()
        self.client.post(
            self.BG_URL,
            {
                "bg_type": "CONTRACTOR",
                "bg_name": "Performance BG",
                "due_date": "2026-06-17",
                "updated_date": "2026-06-15",
            },
            format="json",
        )
        response = self.client.get(self.BY_PROJECT_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["data"]
        self.assertEqual(len(data["contractor_bg"]), 1)
        self.assertEqual(data["contractor_bg"][0]["status"], BG_STATUS_UPDATED)
        self.assertIn("bg_summary", data)
        self.assertNotIn("contractor_bg_due_date", data)

    def test_list_csv_export_includes_bg_summary_columns(self):
        self._create_schedule_records()
        self.client.post(
            self.BG_URL,
            {
                "bg_type": "CONTRACTOR",
                "bg_name": "Performance BG",
                "due_date": "2026-06-17",
                "updated_date": "2026-06-15",
            },
            format="json",
        )
        response = self.client.get(f"{self.LIST_URL}?export=csv")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.content.decode()
        self.assertIn("bg_total", body)
        self.assertIn("bg_compliance_percentage", body)
        self.assertIn("100.0", body)

    def test_by_project_without_bg_entries(self):
        self._create_schedule_records()
        response = self.client.get(self.BY_PROJECT_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["contractor_bg"], [])
        self.assertEqual(response.data["data"]["scl_bg"], [])
        self.assertEqual(response.data["data"]["bg_summary"]["total_bg"], 0)
