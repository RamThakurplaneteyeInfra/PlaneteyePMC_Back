"""Tests for Project Dates and multi-entry BG Status."""

from datetime import date

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from core.test_auth import authenticate_client
from contractors.models import Contractor
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
            contractor_name="Contractor",
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


class LegacyBGMigrationTest(TestCase):
    """Verify legacy-style BG data maps to multi-entry BGStatus payload."""

    def test_legacy_bg_rows_produce_expected_payload(self):
        project = Project.objects.create(name="Legacy Project")
        contractor = ProjectDates.objects.create(
            project=project,
            date_type=ProjectDates.DATE_TYPE_CONTRACTOR,
            contractor_name="Contractor",
            project_start=date(2024, 1, 1),
            contract_finish=date(2026, 1, 1),
            forecast_finish=date(2026, 3, 1),
            eot_date=date(2026, 6, 1),
        )
        scl = ProjectDates.objects.create(
            project=project,
            date_type=ProjectDates.DATE_TYPE_SCL,
            project_start=date(2024, 1, 1),
            contract_finish=date(2026, 1, 1),
            forecast_finish=date(2026, 3, 1),
            eot_date=date(2026, 6, 1),
        )
        BGStatus.objects.create(
            project_date=contractor,
            bg_type=BGStatus.BG_TYPE_CONTRACTOR,
            bg_name="Contractor BG",
            due_date=date(2026, 6, 17),
            updated_date=date(2026, 6, 15),
        )
        BGStatus.objects.create(
            project_date=scl,
            bg_type=BGStatus.BG_TYPE_SCL,
            bg_name="SCL BG",
            due_date=date(2026, 6, 18),
            updated_date=None,
        )

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
            contractor_name="Contractor",
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
        scl_record = next(r for r in records if r["date_type"] == "SCL")
        bg = scl_record["bg_status"]
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
                "contractor_name": "Contractor",
            },
            format="json",
        )
        response = self.client.get(self.BY_PROJECT_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["data"]
        self.assertIn("contractors", data)
        self.assertEqual(len(data["contractors"]), 1)
        self.assertEqual(data["contractors"][0]["contractor_name"], "Contractor")
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
        self.assertIn("contractor_name", body)
        self.assertIn("100.0", body)

    def test_by_project_without_bg_entries(self):
        self._create_schedule_records()
        response = self.client.get(self.BY_PROJECT_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["contractor_bg"], [])
        self.assertEqual(response.data["data"]["scl_bg"], [])
        self.assertEqual(response.data["data"]["bg_summary"]["total_bg"], 0)


class MultiContractorProjectDatesAPITest(APITestCase):
    CREATE_URL = "/api/project-dates/"
    BY_PROJECT_URL = "/api/project-dates/project/Thane%20Project/"
    BG_URL = "/api/project-dates/project/Thane%20Project/bg-status/"

    def setUp(self):
        self.project = Project.objects.create(name="Thane Project")
        authenticate_client(self.client)
        ProjectDates.objects.filter(project=self.project).delete()
        Contractor.objects.filter(project=self.project).delete()

    def _ensure_contractor(self, name: str) -> int:
        contractor, _ = Contractor.objects.get_or_create(
            project=self.project,
            contractor_name=name,
            defaults={"status": Contractor.Status.ACTIVE},
        )
        return contractor.id

    def _create_scl(self):
        return self.client.post(
            self.CREATE_URL,
            {
                "project_name": "Thane Project",
                "date_type": "SCL",
                "project_start": "2024-06-01",
                "contract_finish": "2026-06-01",
                "forecast_finish": "2026-09-01",
                "eot_date": "2026-12-01",
            },
            format="json",
        )

    def _create_contractor(self, name, start="2024-06-01"):
        contractor_id = self._ensure_contractor(name)
        return self.client.post(
            self.CREATE_URL,
            {
                "project_name": "Thane Project",
                "date_type": "CONTRACTOR",
                "contractor_id": contractor_id,
                "project_start": start,
                "contract_finish": "2026-06-01",
                "forecast_finish": "2026-09-01",
                "eot_date": "2026-12-01",
            },
            format="json",
        )

    def test_create_multiple_contractors(self):
        self._create_scl()
        r1 = self._create_contractor("ABC Infra")
        r2 = self._create_contractor("XYZ Construction", start="2024-07-01")
        self.assertEqual(r1.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r2.status_code, status.HTTP_201_CREATED)

        response = self.client.get(self.BY_PROJECT_URL)
        data = response.data["data"]
        self.assertEqual(len(data["contractors"]), 2)
        names = {c["contractor_name"] for c in data["contractors"]}
        self.assertEqual(names, {"ABC Infra", "XYZ Construction"})
        self.assertEqual(data["contractor"]["contractor_name"], "ABC Infra")

    def test_duplicate_contractor_name_rejected(self):
        self._create_contractor("ABC Infra")
        response = self._create_contractor("ABC Infra")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("contractor_id", response.data["errors"])

    def test_contractor_name_required_for_contractor_type(self):
        response = self.client.post(
            self.CREATE_URL,
            {
                "project_name": "Thane Project",
                "date_type": "CONTRACTOR",
                "project_start": "2024-06-01",
                "contract_finish": "2026-06-01",
                "forecast_finish": "2026-09-01",
                "eot_date": "2026-12-01",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("contractor_id", response.data["errors"])

    def test_delete_one_contractor_leaves_others(self):
        self._create_contractor("ABC Infra")
        r2 = self._create_contractor("XYZ Construction")
        contractor_b_id = r2.data["data"]["id"]

        delete_response = self.client.delete(f"{self.CREATE_URL}{contractor_b_id}/")
        self.assertEqual(delete_response.status_code, status.HTTP_200_OK)

        response = self.client.get(self.BY_PROJECT_URL)
        contractors = response.data["data"]["contractors"]
        self.assertEqual(len(contractors), 1)
        self.assertEqual(contractors[0]["contractor_name"], "ABC Infra")

    def test_bg_scoped_per_contractor(self):
        self._create_contractor("ABC Infra")
        self._create_contractor("XYZ Construction")

        self.client.post(
            self.BG_URL,
            {
                "bg_type": "CONTRACTOR",
                "contractor_name": "ABC Infra",
                "bg_name": "ABC Performance BG",
                "due_date": "2026-06-15",
                "updated_date": "2026-06-14",
            },
            format="json",
        )
        self.client.post(
            self.BG_URL,
            {
                "bg_type": "CONTRACTOR",
                "contractor_name": "XYZ Construction",
                "bg_name": "XYZ Security BG",
                "due_date": "2026-06-20",
            },
            format="json",
        )

        response = self.client.get(self.BY_PROJECT_URL)
        contractors = response.data["data"]["contractors"]
        abc = next(c for c in contractors if c["contractor_name"] == "ABC Infra")
        xyz = next(c for c in contractors if c["contractor_name"] == "XYZ Construction")

        self.assertEqual(len(abc["bg_status"]["contractor_bg"]), 1)
        self.assertEqual(abc["bg_status"]["contractor_bg"][0]["bg_name"], "ABC Performance BG")
        self.assertEqual(len(xyz["bg_status"]["contractor_bg"]), 1)
        self.assertEqual(xyz["bg_status"]["contractor_bg"][0]["bg_name"], "XYZ Security BG")

    def test_get_bg_status_filtered_by_contractor_name(self):
        self._create_contractor("ABC Infra")
        self._create_contractor("XYZ Construction")
        self.client.post(
            self.BG_URL,
            {
                "bg_type": "CONTRACTOR",
                "contractor_name": "ABC Infra",
                "bg_name": "ABC BG",
                "due_date": "2026-06-15",
            },
            format="json",
        )
        self.client.post(
            self.BG_URL,
            {
                "bg_type": "CONTRACTOR",
                "contractor_name": "XYZ Construction",
                "bg_name": "XYZ BG",
                "due_date": "2026-06-20",
            },
            format="json",
        )

        response = self.client.get(f"{self.BG_URL}?contractor_name=ABC%20Infra")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["data"]["contractor_bg"]), 1)
        self.assertEqual(response.data["data"]["contractor_bg"][0]["bg_name"], "ABC BG")
        self.assertEqual(response.data["data"]["scl_bg"], [])

    def test_get_bg_status_filtered_by_contractor_id(self):
        abc_id = self._ensure_contractor("ABC Infra")
        xyz_id = self._ensure_contractor("XYZ Construction")
        self._create_contractor("ABC Infra")
        self._create_contractor("XYZ Construction")

        self.client.post(
            self.BG_URL,
            {
                "bg_type": "CONTRACTOR",
                "contractor_id": abc_id,
                "bg_name": "ABC BG",
                "due_date": "2026-06-15",
            },
            format="json",
        )
        self.client.post(
            self.BG_URL,
            {
                "bg_type": "CONTRACTOR",
                "contractor_id": xyz_id,
                "bg_name": "XYZ BG",
                "due_date": "2026-06-20",
            },
            format="json",
        )

        abc_response = self.client.get(f"{self.BG_URL}?contractor_id={abc_id}")
        self.assertEqual(abc_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(abc_response.data["data"]["contractor_bg"]), 1)
        self.assertEqual(abc_response.data["data"]["contractor_bg"][0]["bg_name"], "ABC BG")

        xyz_response = self.client.get(f"{self.BG_URL}?contractor_id={xyz_id}")
        self.assertEqual(xyz_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(xyz_response.data["data"]["contractor_bg"]), 1)
        self.assertEqual(xyz_response.data["data"]["contractor_bg"][0]["bg_name"], "XYZ BG")

    def test_get_by_project_returns_isolated_contractor_schedules(self):
        self._create_contractor("ABC Infra", start="2024-06-01")
        self._create_contractor("XYZ Construction", start="2024-08-01")

        response = self.client.get(self.BY_PROJECT_URL)
        contractors = response.data["data"]["contractors"]
        abc = next(c for c in contractors if c["contractor"]["id"] == self._ensure_contractor("ABC Infra"))
        xyz = next(c for c in contractors if c["contractor"]["id"] == self._ensure_contractor("XYZ Construction"))

        self.assertEqual(abc["project_start"], "2024-06-01")
        self.assertEqual(xyz["project_start"], "2024-08-01")
        self.assertEqual(abc["contractor"]["contractor_name"], "ABC Infra")
        self.assertEqual(xyz["contractor"]["contractor_name"], "XYZ Construction")
