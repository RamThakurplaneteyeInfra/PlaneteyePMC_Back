"""
Tests for Drawing Register and KPI summary.

DrawingRegisterItem is the single source of truth.
KPI metrics are computed directly from register records — no DrawingSummary seeding.
"""

from datetime import date
from unittest.mock import patch
import uuid

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


def _fake_drawing_upload(**kwargs):
    uploaded_file = kwargs["uploaded_file"]
    name = getattr(uploaded_file, "name", "drawing.pdf")
    ext = name.rsplit(".", 1)[-1]
    pid = kwargs["project_id"]
    rid = kwargs["register_id"]
    rev = kwargs["revision"]
    unique = uuid.uuid4().hex
    return {
        "s3_key": f"Drawing/{pid}/{rid}/rev-{rev}/{unique}.{ext}",
        "file_url": f"https://example.s3.amazonaws.com/Drawing/{pid}/{rid}/rev-{rev}/{unique}.{ext}",
        "original_filename": name.split("/")[-1],
        "file_size": int(getattr(uploaded_file, "size", 20) or 20),
        "content_type": "application/pdf" if ext == "pdf" else "application/acad",
        "file_extension": ext,
    }


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


class DrawingFileUploadAPITest(APITestCase):
    REGISTER_URL = "/api/drawings/register/"

    def setUp(self):
        self.project = Project.objects.create(name="Thane Project")
        authenticate_client(self.client)

    @staticmethod
    def _pdf(name="drawing.pdf"):
        from django.core.files.uploadedfile import SimpleUploadedFile

        return SimpleUploadedFile(
            name,
            b"%PDF-1.4\nfake pdf content\n",
            content_type="application/pdf",
        )

    @staticmethod
    def _dwg(name="drawing.dwg"):
        from django.core.files.uploadedfile import SimpleUploadedFile

        return SimpleUploadedFile(
            name,
            b"AC1015\nfake dwg content\n",
            content_type="application/acad",
        )

    @patch("drawings.services.file_upload.upload_drawing_file", side_effect=_fake_drawing_upload)
    @patch("services.s3_drawing_files.check_s3_ready", return_value=(True, None))
    def test_create_without_files_json_only(self, _ready, _upload):
        payload = {
            "project_name": "Thane Project",
            "drawing_name": "Column Layout",
            "revision": 1,
        }
        response = self.client.post(self.REGISTER_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.data["data"]
        self.assertEqual(data["drawing_name"], "Column Layout")
        self.assertEqual(data["drawings"], [])

    @patch("drawings.services.file_upload.upload_drawing_file", side_effect=_fake_drawing_upload)
    @patch("services.s3_drawing_files.check_s3_ready", return_value=(True, None))
    def test_create_with_one_file(self, _ready, _upload):
        response = self.client.post(
            self.REGISTER_URL,
            {
                "project_name": "Thane Project",
                "drawing_name": "Column Layout",
                "revision": 1,
                "drawings": self._pdf("column.pdf"),
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        drawings = response.data["data"]["drawings"]
        self.assertEqual(len(drawings), 1)
        self.assertEqual(drawings[0]["original_filename"], "column.pdf")
        self.assertEqual(drawings[0]["revision"], 1)

    @patch("drawings.services.file_upload.upload_drawing_file", side_effect=_fake_drawing_upload)
    @patch("services.s3_drawing_files.check_s3_ready", return_value=(True, None))
    def test_create_with_multiple_files(self, _ready, _upload):
        response = self.client.post(
            self.REGISTER_URL,
            {
                "project_name": "Thane Project",
                "drawing_name": "Column Layout",
                "revision": 1,
                "drawings": [self._pdf("a.pdf"), self._dwg("a.dwg"), self._pdf("b.pdf")],
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(response.data["data"]["drawings"]), 3)

    @patch("services.s3_drawing_files.validate_upload_file")
    @patch("drawings.services.file_upload.upload_drawing_file", side_effect=_fake_drawing_upload)
    @patch("services.s3_drawing_files.check_s3_ready", return_value=(True, None))
    def test_invalid_extension_rejected(self, _ready, _upload, mock_validate):
        from django.core.exceptions import ValidationError
        from django.core.files.uploadedfile import SimpleUploadedFile

        mock_validate.side_effect = ValidationError("Unsupported file type '.exe'.")
        response = self.client.post(
            self.REGISTER_URL,
            {
                "project_name": "Thane Project",
                "drawing_name": "Bad File",
                "revision": 1,
                "drawings": SimpleUploadedFile(
                    "virus.exe", b"MZ", content_type="application/octet-stream"
                ),
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(DrawingRegisterItem.objects.count(), 0)

    @patch("drawings.services.file_upload.upload_drawing_file", side_effect=_fake_drawing_upload)
    @patch("services.s3_drawing_files.check_s3_ready", return_value=(True, None))
    def test_patch_adds_files_at_current_revision(self, _ready, _upload):
        from .models.drawing_file import DrawingFile

        item = DrawingRegisterItem.objects.create(
            project=self.project,
            sr_no=1,
            drawing_name="Roof Plan",
            revision=1,
        )
        DrawingFile.objects.create(
            drawing_register=item,
            revision=1,
            original_filename="rev1.pdf",
            s3_key="Drawing/1/1/rev-1/old.pdf",
            file_url="https://example.com/old.pdf",
            file_size=100,
            content_type="application/pdf",
            file_extension="pdf",
            is_active=True,
        )
        item.revision = 2
        item.save(update_fields=["revision", "updated_at"])

        url = f"{self.REGISTER_URL}{item.id}/"
        response = self.client.patch(
            url,
            {"drawings": [self._pdf("rev2.pdf"), self._dwg("rev2.dwg")]},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        drawings = response.data["data"]["drawings"]
        self.assertEqual(len(drawings), 3)
        rev2 = [d for d in drawings if d["revision"] == 2]
        self.assertEqual(len(rev2), 2)

    @patch("services.s3_drawing_files.delete_drawing_file")
    @patch("drawings.services.file_upload.upload_drawing_file", side_effect=_fake_drawing_upload)
    @patch("services.s3_drawing_files.check_s3_ready", return_value=(True, None))
    def test_delete_file_soft_deletes(self, _ready, _upload, mock_s3_del):
        create = self.client.post(
            self.REGISTER_URL,
            {
                "project_name": "Thane Project",
                "drawing_name": "Deletable",
                "revision": 1,
                "drawings": self._pdf(),
            },
            format="multipart",
        )
        file_id = create.data["data"]["drawings"][0]["id"]
        response = self.client.delete(f"/api/drawings/files/{file_id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        from .models.drawing_file import DrawingFile

        self.assertFalse(DrawingFile.objects.get(pk=file_id).is_active)
        mock_s3_del.assert_called_once()

    @patch("drawings.controllers.drawing_register_controller.delete_register_s3_files")
    @patch("drawings.services.file_upload.upload_drawing_file", side_effect=_fake_drawing_upload)
    @patch("services.s3_drawing_files.check_s3_ready", return_value=(True, None))
    def test_delete_register_cleans_s3(self, _ready, _upload, mock_cleanup):
        create = self.client.post(
            self.REGISTER_URL,
            {
                "project_name": "Thane Project",
                "drawing_name": "Whole Register",
                "revision": 1,
                "drawings": self._pdf(),
            },
            format="multipart",
        )
        item_id = create.data["data"]["id"]
        response = self.client.delete(f"{self.REGISTER_URL}{item_id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_cleanup.assert_called_once()
        self.assertEqual(DrawingRegisterItem.objects.count(), 0)

    @patch("drawings.services.file_upload.upload_drawing_file", side_effect=_fake_drawing_upload)
    @patch("services.s3_drawing_files.check_s3_ready", return_value=(True, None))
    def test_workflow_events_unchanged_with_files(self, _ready, _upload):
        response = self.client.post(
            self.REGISTER_URL,
            {
                "project_name": "Thane Project",
                "drawing_name": "Workflow Drawing",
                "revision": 1,
                "workflow_events": '[{"action":"SUBMITTED","event_date":"2026-03-01"}]',
                "drawings": self._pdf(),
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        events = response.data["data"]["workflow_events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["action"], "SUBMITTED")

    @patch("drawings.services.file_upload.upload_drawing_file", side_effect=_fake_drawing_upload)
    @patch("services.s3_drawing_files.check_s3_ready", return_value=(True, None))
    def test_audit_log_on_upload(self, _ready, _upload):
        from core.models import BusinessAuditLog

        self.client.post(
            self.REGISTER_URL,
            {
                "project_name": "Thane Project",
                "drawing_name": "Audited",
                "revision": 1,
                "drawings": self._pdf(),
            },
            format="multipart",
        )
        self.assertTrue(
            BusinessAuditLog.objects.filter(
                entity_type=BusinessAuditLog.ENTITY_DRAWING,
                action=BusinessAuditLog.ACTION_UPLOADED,
            ).exists()
        )

    @patch("drawings.services.file_upload.upload_drawing_file", side_effect=_fake_drawing_upload)
    @patch("services.s3_drawing_files.check_s3_ready", return_value=(True, None))
    def test_summary_includes_drawing_file_count(self, _ready, _upload):
        self.client.post(
            self.REGISTER_URL,
            {
                "project_name": "Thane Project",
                "drawing_name": "Summary Drawing",
                "revision": 1,
                "submitted_date": "2026-06-01",
                "drawings": [self._pdf("a.pdf"), self._pdf("b.pdf")],
            },
            format="multipart",
        )
        response = self.client.get(
            "/api/drawings/project/Thane%20Project/summary/",
            {"month": 6, "year": 2026},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["drawing_file_count"], 2)

    @patch("drawings.services.file_upload.delete_drawing_files_batch")
    @patch("drawings.services.file_upload.upload_drawing_file")
    @patch("services.s3_drawing_files.check_s3_ready", return_value=(True, None))
    def test_multiple_upload_failure_cleans_s3(self, _ready, mock_upload, mock_cleanup):
        def _side_effect(**kwargs):
            if getattr(kwargs["uploaded_file"], "name", "").endswith("b.pdf"):
                raise Exception("S3 failed")
            return _fake_drawing_upload(**kwargs)

        mock_upload.side_effect = _side_effect
        response = self.client.post(
            self.REGISTER_URL,
            {
                "project_name": "Thane Project",
                "drawing_name": "Fail Mid Upload",
                "revision": 1,
                "drawings": [self._pdf("a.pdf"), self._pdf("b.pdf")],
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(DrawingRegisterItem.objects.count(), 0)
        mock_cleanup.assert_called()
