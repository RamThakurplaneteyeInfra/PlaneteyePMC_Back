"""Tests for Project Dates and BG Status."""

from datetime import date

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from core.test_auth import authenticate_client
from projects.models import Project

from .bg_status import bg_status_dict, upsert_bg_status
from .models import ProjectBGStatus, ProjectDates


class BGStatusHelperTest(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name="Thane Project")

    def test_empty_bg_status_when_no_record(self):
        self.assertEqual(
            bg_status_dict(self.project),
            {"contractor_bg_date": None, "scl_bg_date": None},
        )

    def test_upsert_partial_dates(self):
        upsert_bg_status(self.project, {"contractor_bg_date": date(2026, 1, 15)})
        payload = bg_status_dict(self.project)
        self.assertEqual(payload["contractor_bg_date"], "2026-01-15")
        self.assertIsNone(payload["scl_bg_date"])

        upsert_bg_status(self.project, {"scl_bg_date": date(2026, 2, 1)})
        payload = bg_status_dict(self.project)
        self.assertEqual(payload["contractor_bg_date"], "2026-01-15")
        self.assertEqual(payload["scl_bg_date"], "2026-02-01")

    def test_clear_date_with_null(self):
        upsert_bg_status(
            self.project,
            {
                "contractor_bg_date": date(2026, 1, 15),
                "scl_bg_date": date(2026, 2, 1),
            },
        )
        upsert_bg_status(self.project, {"contractor_bg_date": None})
        payload = bg_status_dict(self.project)
        self.assertIsNone(payload["contractor_bg_date"])
        self.assertEqual(payload["scl_bg_date"], "2026-02-01")


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

    def test_get_bg_status_empty(self):
        response = self.client.get(self.BG_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(
            response.data["data"],
            {"contractor_bg_date": None, "scl_bg_date": None},
        )

    def test_post_creates_bg_status(self):
        response = self.client.post(
            self.BG_URL,
            {
                "contractor_bg_date": "2026-03-10",
                "scl_bg_date": "2026-04-01",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["data"]["contractor_bg_date"], "2026-03-10")
        self.assertEqual(response.data["data"]["scl_bg_date"], "2026-04-01")

    def test_post_upserts_existing_record(self):
        self.client.post(
            self.BG_URL,
            {"contractor_bg_date": "2026-03-10"},
            format="json",
        )
        response = self.client.post(
            self.BG_URL,
            {"scl_bg_date": "2026-05-01"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["contractor_bg_date"], "2026-03-10")
        self.assertEqual(response.data["data"]["scl_bg_date"], "2026-05-01")

    def test_patch_contractor_bg_date_only(self):
        response = self.client.patch(
            self.BG_URL,
            {"contractor_bg_date": "2026-03-10"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["contractor_bg_date"], "2026-03-10")
        self.assertIsNone(response.data["data"]["scl_bg_date"])

    def test_patch_scl_bg_date_independently(self):
        self.client.patch(
            self.BG_URL,
            {"contractor_bg_date": "2026-03-10"},
            format="json",
        )
        response = self.client.patch(
            self.BG_URL,
            {"scl_bg_date": "2026-04-20"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["contractor_bg_date"], "2026-03-10")
        self.assertEqual(response.data["data"]["scl_bg_date"], "2026-04-20")

    def test_list_includes_bg_status(self):
        self._create_scl_record()
        self.client.patch(
            self.BG_URL,
            {"scl_bg_date": "2026-05-01"},
            format="json",
        )
        response = self.client.get(self.LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        records = response.data["data"]["results"]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["bg_status"]["scl_bg_date"], "2026-05-01")
        self.assertIsNone(records[0]["bg_status"]["contractor_bg_date"])

    def test_by_project_includes_bg_status(self):
        self._create_scl_record()
        self.client.patch(
            self.BG_URL,
            {
                "contractor_bg_date": "2026-06-01",
                "scl_bg_date": "2026-06-15",
            },
            format="json",
        )
        response = self.client.get(self.BY_PROJECT_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        bg = response.data["data"]["bg_status"]
        self.assertEqual(bg["contractor_bg_date"], "2026-06-01")
        self.assertEqual(bg["scl_bg_date"], "2026-06-15")

    def test_list_csv_export_includes_bg_columns(self):
        self._create_scl_record()
        self.client.patch(
            self.BG_URL,
            {"contractor_bg_date": "2026-07-01"},
            format="json",
        )
        response = self.client.get(f"{self.LIST_URL}?export=csv")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("text/csv", response["Content-Type"])
        body = response.content.decode()
        self.assertIn("contractor_bg_date", body)
        self.assertIn("2026-07-01", body)

    def test_legacy_record_without_bg_status(self):
        self._create_scl_record()
        response = self.client.get(self.BY_PROJECT_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["data"]["bg_status"],
            {"contractor_bg_date": None, "scl_bg_date": None},
        )
