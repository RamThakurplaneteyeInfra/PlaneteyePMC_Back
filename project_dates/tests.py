"""Tests for Project Dates and BG Status."""

from datetime import date

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from core.test_auth import authenticate_client
from projects.models import Project

from .bg_serializers import ProjectBGStatusSerializer
from .bg_status import (
    BG_STATUS_NOT_UPDATED,
    BG_STATUS_UPDATED,
    BG_STATUS_YET_TO_UPDATE,
    bg_status_dict,
    calculate_bg_status,
    upsert_bg_status,
)
from .models import ProjectBGStatus, ProjectDates


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

    def test_null_dates(self):
        self.assertEqual(
            calculate_bg_status(None, None),
            BG_STATUS_YET_TO_UPDATE,
        )


class ProjectBGStatusSerializerTest(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name="Thane Project")

    def test_serializer_calculates_contractor_and_scl_statuses(self):
        upsert_bg_status(
            self.project,
            {
                "contractor_bg_due_date": date(2026, 6, 17),
                "contractor_bg_updated_date": date(2026, 6, 15),
                "scl_bg_due_date": date(2026, 6, 17),
                "scl_bg_updated_date": None,
            },
        )

        serializer = ProjectBGStatusSerializer(ProjectBGStatus.objects.get(project=self.project))

        self.assertEqual(serializer.data["contractor_bg_status"], BG_STATUS_UPDATED)
        self.assertEqual(serializer.data["scl_bg_status"], BG_STATUS_YET_TO_UPDATE)


class ProjectDatesBGStatusAPITest(APITestCase):
    LIST_URL = "/api/project-dates/"
    BG_URL = "/api/project-dates/project/Thane%20Project/bg-status/"
    BY_PROJECT_URL = "/api/project-dates/project/Thane%20Project/"

    def setUp(self):
        self.project = Project.objects.create(name="Thane Project")
        authenticate_client(self.client)
        ProjectDates.objects.filter(project=self.project).delete()
        ProjectBGStatus.objects.filter(project=self.project).delete()

    def _create_scl_record(self):
        return ProjectDates.objects.create(
            project=self.project,
            date_type=ProjectDates.DATE_TYPE_SCL,
            project_start=date(2024, 6, 1),
            contract_finish=date(2026, 6, 1),
            forecast_finish=date(2026, 9, 1),
            eot_date=date(2026, 12, 1),
        )

    def _empty_bg_payload(self):
        return {
            "contractor_bg_date": None,
            "contractor_bg_due_date": None,
            "contractor_bg_updated_date": None,
            "contractor_bg_status": BG_STATUS_YET_TO_UPDATE,
            "scl_bg_date": None,
            "scl_bg_due_date": None,
            "scl_bg_updated_date": None,
            "scl_bg_status": BG_STATUS_YET_TO_UPDATE,
        }

    def test_get_bg_status_empty(self):
        response = self.client.get(self.BG_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["data"], self._empty_bg_payload())

    def test_post_creates_bg_status_with_due_and_updated_dates(self):
        response = self.client.post(
            self.BG_URL,
            {
                "contractor_bg_due_date": "2026-06-17",
                "contractor_bg_updated_date": "2026-06-15",
                "scl_bg_due_date": "2026-06-17",
                "scl_bg_updated_date": None,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["data"]["contractor_bg_due_date"], "2026-06-17")
        self.assertEqual(response.data["data"]["contractor_bg_updated_date"], "2026-06-15")
        self.assertEqual(response.data["data"]["contractor_bg_status"], BG_STATUS_UPDATED)
        self.assertEqual(response.data["data"]["scl_bg_due_date"], "2026-06-17")
        self.assertIsNone(response.data["data"]["scl_bg_updated_date"])
        self.assertEqual(response.data["data"]["scl_bg_status"], BG_STATUS_YET_TO_UPDATE)

    def test_post_upserts_existing_record(self):
        self.client.post(
            self.BG_URL,
            {
                "contractor_bg_due_date": "2026-06-17",
                "contractor_bg_updated_date": "2026-06-15",
            },
            format="json",
        )
        response = self.client.post(
            self.BG_URL,
            {
                "scl_bg_due_date": "2026-06-17",
                "scl_bg_updated_date": "2026-06-20",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["contractor_bg_status"], BG_STATUS_UPDATED)
        self.assertEqual(response.data["data"]["scl_bg_status"], BG_STATUS_NOT_UPDATED)

    def test_patch_contractor_bg_due_date_only(self):
        response = self.client.patch(
            self.BG_URL,
            {"contractor_bg_due_date": "2026-06-17"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["contractor_bg_due_date"], "2026-06-17")
        self.assertEqual(response.data["data"]["contractor_bg_status"], BG_STATUS_YET_TO_UPDATE)
        self.assertIsNone(response.data["data"]["contractor_bg_updated_date"])

    def test_patch_scl_bg_updated_date_independently(self):
        self.client.patch(
            self.BG_URL,
            {"contractor_bg_due_date": "2026-06-17"},
            format="json",
        )
        response = self.client.patch(
            self.BG_URL,
            {"scl_bg_updated_date": "2026-06-16"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["contractor_bg_due_date"], "2026-06-17")
        self.assertEqual(response.data["data"]["contractor_bg_status"], BG_STATUS_YET_TO_UPDATE)
        self.assertEqual(response.data["data"]["scl_bg_updated_date"], "2026-06-16")
        self.assertEqual(response.data["data"]["scl_bg_status"], BG_STATUS_YET_TO_UPDATE)

    def test_legacy_bg_date_fields_remain_writable(self):
        response = self.client.post(
            self.BG_URL,
            {
                "contractor_bg_date": "2026-06-15",
                "scl_bg_date": "2026-06-20",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["data"]["contractor_bg_date"], "2026-06-15")
        self.assertEqual(response.data["data"]["contractor_bg_updated_date"], "2026-06-15")
        self.assertEqual(response.data["data"]["scl_bg_date"], "2026-06-20")
        self.assertEqual(response.data["data"]["scl_bg_updated_date"], "2026-06-20")

    def test_list_includes_bg_status(self):
        self._create_scl_record()
        self.client.patch(
            self.BG_URL,
            {
                "scl_bg_due_date": "2026-06-17",
                "scl_bg_updated_date": "2026-06-15",
            },
            format="json",
        )
        response = self.client.get(self.LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        records = response.data["data"]["results"]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["bg_status"]["scl_bg_due_date"], "2026-06-17")
        self.assertEqual(records[0]["bg_status"]["scl_bg_updated_date"], "2026-06-15")
        self.assertEqual(records[0]["bg_status"]["scl_bg_status"], BG_STATUS_UPDATED)
        self.assertIsNone(records[0]["bg_status"]["contractor_bg_updated_date"])
        self.assertEqual(
            records[0]["bg_status"]["contractor_bg_status"],
            BG_STATUS_YET_TO_UPDATE,
        )

    def test_by_project_includes_bg_status(self):
        self._create_scl_record()
        self.client.patch(
            self.BG_URL,
            {
                "contractor_bg_due_date": "2026-06-17",
                "contractor_bg_updated_date": "2026-06-15",
                "scl_bg_due_date": "2026-06-17",
                "scl_bg_updated_date": None,
            },
            format="json",
        )
        response = self.client.get(self.BY_PROJECT_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        bg = response.data["data"]["bg_status"]
        self.assertEqual(bg["contractor_bg_due_date"], "2026-06-17")
        self.assertEqual(bg["contractor_bg_updated_date"], "2026-06-15")
        self.assertEqual(bg["contractor_bg_status"], BG_STATUS_UPDATED)
        self.assertEqual(bg["scl_bg_due_date"], "2026-06-17")
        self.assertIsNone(bg["scl_bg_updated_date"])
        self.assertEqual(bg["scl_bg_status"], BG_STATUS_YET_TO_UPDATE)

    def test_list_csv_export_includes_bg_columns(self):
        self._create_scl_record()
        self.client.patch(
            self.BG_URL,
            {
                "contractor_bg_due_date": "2026-06-17",
                "contractor_bg_updated_date": "2026-06-15",
            },
            format="json",
        )
        response = self.client.get(f"{self.LIST_URL}?export=csv")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("text/csv", response["Content-Type"])
        body = response.content.decode()
        self.assertIn("contractor_bg_due_date", body)
        self.assertIn("contractor_bg_updated_date", body)
        self.assertIn("contractor_bg_status", body)
        self.assertIn("2026-06-17", body)
        self.assertIn("2026-06-15", body)
        self.assertIn(BG_STATUS_UPDATED, body)

    def test_legacy_record_without_bg_status(self):
        self._create_scl_record()
        response = self.client.get(self.BY_PROJECT_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["bg_status"], self._empty_bg_payload())
