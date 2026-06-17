"""
Tests for Drawing Register and KPI summary.

DrawingRegisterItem is the single source of truth.
KPI metrics are computed directly from register records — no DrawingSummary seeding.
"""

from datetime import date

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from core.test_auth import authenticate_client
from projects.models import Project

from .controllers.drawing_report import (
    VIEW_CUMULATIVE,
    VIEW_MONTHLY,
    build_client_row,
    filter_register_queryset,
    kpi_summary_for_period,
)
from .models.drawing_register import DrawingRegisterItem, DrawingWorkflowEvent


class DrawingClientReportTest(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name="Thane Project")

    def test_build_client_row_from_workflow_events(self):
        item = DrawingRegisterItem.objects.create(
            project=self.project,
            sr_no=1,
            drawing_name="Pile Foundation Drawing",
            remarks="Approved",
        )
        DrawingWorkflowEvent.objects.create(
            drawing=item,
            action=DrawingWorkflowEvent.ACTION_SUBMITTED,
            event_date=date(2025, 9, 19),
        )
        DrawingWorkflowEvent.objects.create(
            drawing=item,
            action=DrawingWorkflowEvent.ACTION_CONSULTANT_COMMENTED,
            event_date=date(2025, 10, 19),
        )
        DrawingWorkflowEvent.objects.create(
            drawing=item,
            action=DrawingWorkflowEvent.ACTION_RESUBMITTED,
            event_date=date(2025, 12, 19),
        )
        DrawingWorkflowEvent.objects.create(
            drawing=item,
            action=DrawingWorkflowEvent.ACTION_APPROVED,
            event_date=date(2025, 12, 30),
        )

        row = build_client_row(item)
        self.assertEqual(row["sr_no"], 1)
        self.assertEqual(row["design_and_drawing"], "Pile Foundation Drawing")
        self.assertEqual(row["submission_by_contractor"], "2025-09-19")
        self.assertEqual(row["consultant_comments_date"], "2025-10-19")
        self.assertEqual(row["resubmission_date"], "2025-12-19")
        self.assertEqual(row["approved_by_consultant"], "2025-12-30")
        self.assertEqual(row["remarks"], "Approved")

    def test_build_client_row_missing_stages_return_null(self):
        item = DrawingRegisterItem.objects.create(
            project=self.project,
            sr_no=2,
            drawing_name="Roof Plan",
            submitted_date=date(2026, 1, 5),
        )
        row = build_client_row(item)
        self.assertEqual(row["submission_by_contractor"], "2026-01-05")
        self.assertIsNone(row["consultant_comments_date"])
        self.assertIsNone(row["resubmission_date"])
        self.assertIsNone(row["approved_by_consultant"])


class DrawingClientReportAPITest(APITestCase):
    PROJECT_SUMMARY_URL = "/api/drawings/project/Thane%20Project/summary/"

    def setUp(self):
        self.project = Project.objects.create(name="Thane Project")
        authenticate_client(self.client)
        DrawingRegisterItem.objects.filter(project=self.project).delete()

    def _create_sample_row(self, sr_no=1):
        """One drawing submitted and approved in Dec 2025."""
        item = DrawingRegisterItem.objects.create(
            project=self.project,
            sr_no=sr_no,
            drawing_name="Pile Foundation Drawing",
            contractor_name="ABC Contractors",
            remarks="Approved",
        )
        DrawingWorkflowEvent.objects.create(
            drawing=item,
            action=DrawingWorkflowEvent.ACTION_SUBMITTED,
            event_date=date(2025, 12, 1),
        )
        DrawingWorkflowEvent.objects.create(
            drawing=item,
            action=DrawingWorkflowEvent.ACTION_APPROVED,
            event_date=date(2025, 12, 30),
        )
        return item

    def test_summary_client_format_monthly(self):
        self._create_sample_row()
        response = self.client.get(
            self.PROJECT_SUMMARY_URL,
            {
                "format": "client",
                "month": 12,
                "year": 2025,
                "view": "monthly",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["data"]
        self.assertEqual(data["view"], "monthly")
        self.assertEqual(data["from_date"], "2025-12-01")
        self.assertEqual(data["to_date"], "2025-12-31")
        self.assertEqual(len(data["rows"]), 1)
        self.assertEqual(data["rows"][0]["design_and_drawing"], "Pile Foundation Drawing")

    def test_project_summary_kpi_from_register(self):
        """KPI summary is computed from register records — no DrawingSummary needed."""
        # 3 drawings submitted in June 2026, 2 approved
        for i in range(1, 4):
            item = DrawingRegisterItem.objects.create(
                project=self.project,
                sr_no=i,
                drawing_name=f"Drawing {i}",
            )
            DrawingWorkflowEvent.objects.create(
                drawing=item,
                action=DrawingWorkflowEvent.ACTION_SUBMITTED,
                event_date=date(2026, 6, i),
            )
            if i <= 2:
                DrawingWorkflowEvent.objects.create(
                    drawing=item,
                    action=DrawingWorkflowEvent.ACTION_APPROVED,
                    event_date=date(2026, 6, i + 10),
                )

        response = self.client.get(
            self.PROJECT_SUMMARY_URL,
            {"month": 6, "year": 2026},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["data"]
        self.assertEqual(data["submitted_drawings"], 3)
        self.assertEqual(data["approved_drawings"], 2)
        self.assertEqual(data["variance"], 1)
        self.assertAlmostEqual(data["approval_rate"], 66.67, places=1)

    def test_project_summary_requires_month_and_year(self):
        """summary endpoint must reject requests missing month/year."""
        response = self.client.get(self.PROJECT_SUMMARY_URL)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_project_summary_client_format_cumulative(self):
        """Cumulative view aggregates all drawings from Jan through the given month."""
        # Jan drawing
        jan = DrawingRegisterItem.objects.create(
            project=self.project, sr_no=2, drawing_name="January Drawing", remarks="Pending"
        )
        DrawingWorkflowEvent.objects.create(
            drawing=jan,
            action=DrawingWorkflowEvent.ACTION_SUBMITTED,
            event_date=date(2025, 1, 10),
        )
        # Dec drawing (submitted + approved)
        self._create_sample_row(sr_no=1)

        response = self.client.get(
            self.PROJECT_SUMMARY_URL,
            {"format": "client", "month": 12, "year": 2025, "view": "cumulative"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["data"]
        self.assertEqual(data["view"], "cumulative")
        self.assertEqual(data["from_date"], "2025-01-01")
        self.assertEqual(len(data["rows"]), 2)
        # 2 submitted (Jan + Dec), 1 approved (Dec)
        self.assertEqual(data["summary"]["submitted_drawings"], 2)
        self.assertEqual(data["summary"]["approved_drawings"], 1)

    def test_summary_csv_export(self):
        self._create_sample_row()
        response = self.client.get(
            self.PROJECT_SUMMARY_URL,
            {
                "format": "client",
                "month": 12,
                "year": 2025,
                "export": "csv",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertIn("Pile Foundation Drawing", response.content.decode())

    def test_register_create_and_list(self):
        payload = {
            "project_name": "Thane Project",
            "drawing_name": "Column Layout",
            "contractor_name": "XYZ Ltd",
            "remarks": "Pending",
            "workflow_events": [
                {
                    "action": "SUBMITTED",
                    "event_date": "2026-03-01",
                }
            ],
        }
        create = self.client.post("/api/drawings/register/", payload, format="json")
        self.assertEqual(create.status_code, status.HTTP_201_CREATED)
        self.assertEqual(create.data["data"]["sr_no"], 1)

        listing = self.client.get(
            "/api/drawings/register/",
            {
                "project_name": "Thane Project",
                "format": "client",
                "month": 3,
                "year": 2026,
            },
        )
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        self.assertEqual(len(listing.data["data"]["rows"]), 1)

    def test_monthly_vs_cumulative_register_filter(self):
        jan = DrawingRegisterItem.objects.create(
            project=self.project, sr_no=10, drawing_name="Jan Doc"
        )
        DrawingWorkflowEvent.objects.create(
            drawing=jan,
            action=DrawingWorkflowEvent.ACTION_SUBMITTED,
            event_date=date(2026, 1, 15),
        )
        june = DrawingRegisterItem.objects.create(
            project=self.project, sr_no=11, drawing_name="Jun Doc"
        )
        DrawingWorkflowEvent.objects.create(
            drawing=june,
            action=DrawingWorkflowEvent.ACTION_SUBMITTED,
            event_date=date(2026, 6, 10),
        )
        monthly = filter_register_queryset(
            project_name="Thane Project",
            month=6,
            year=2026,
            view=VIEW_MONTHLY,
        )
        cumulative = filter_register_queryset(
            project_name="Thane Project",
            month=6,
            year=2026,
            view=VIEW_CUMULATIVE,
        )
        self.assertEqual(monthly.count(), 1)
        self.assertEqual(cumulative.count(), 2)

    def test_kpi_summary_monthly_and_cumulative_from_register(self):
        """kpi_summary_for_period counts register items, not DrawingSummary rows."""
        # Jan: 4 submitted, 2 approved
        for i in range(1, 5):
            item = DrawingRegisterItem.objects.create(
                project=self.project, sr_no=i, drawing_name=f"Jan Drawing {i}"
            )
            DrawingWorkflowEvent.objects.create(
                drawing=item,
                action=DrawingWorkflowEvent.ACTION_SUBMITTED,
                event_date=date(2026, 1, i),
            )
            if i <= 2:
                DrawingWorkflowEvent.objects.create(
                    drawing=item,
                    action=DrawingWorkflowEvent.ACTION_APPROVED,
                    event_date=date(2026, 1, i + 15),
                )

        # June: 6 submitted, 5 approved
        for i in range(5, 11):
            item = DrawingRegisterItem.objects.create(
                project=self.project, sr_no=i, drawing_name=f"Jun Drawing {i}"
            )
            DrawingWorkflowEvent.objects.create(
                drawing=item,
                action=DrawingWorkflowEvent.ACTION_SUBMITTED,
                event_date=date(2026, 6, i - 4),
            )
            if i <= 9:
                DrawingWorkflowEvent.objects.create(
                    drawing=item,
                    action=DrawingWorkflowEvent.ACTION_APPROVED,
                    event_date=date(2026, 6, i),
                )

        monthly = kpi_summary_for_period("Thane Project", 6, 2026, VIEW_MONTHLY)
        cumulative = kpi_summary_for_period("Thane Project", 6, 2026, VIEW_CUMULATIVE)

        self.assertEqual(monthly["submitted_drawings"], 6)
        self.assertEqual(monthly["approved_drawings"], 5)
        self.assertEqual(cumulative["submitted_drawings"], 10)
        self.assertEqual(cumulative["approved_drawings"], 7)
