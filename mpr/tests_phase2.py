"""MPR Phase 2 — generate, snapshot, PDF/Excel, download, regenerate."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from construction_progress.models.construction_progress import ConstructionProgress
from core.models import BusinessAuditLog
from project_dates.eot_models import ProjectEOT
from project_dates.models import ProjectDates
from projects.models import Project
from site_images.models import SiteProgressImage

from mpr.models import MPRReport
from mpr.services.excel_renderer import render_excel
from mpr.services.pdf_renderer import render_pdf

User = get_user_model()


@override_settings(MPR_GENERATION_INLINE=True)
class MPRPhase2Base(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.admin = User.objects.create_user(
            username="mpr2_admin",
            email="mpr2_admin@example.com",
            password="pass12345",
            is_staff=True,
            is_superuser=True,
        )
        self.outsider = User.objects.create_user(
            username="mpr2_out",
            email="mpr2_out@example.com",
            password="pass12345",
        )
        self.tl = User.objects.create_user(
            username="mpr2_tl",
            email="mpr2_tl@example.com",
            password="pass12345",
        )
        self.project = Project.objects.create(
            name="B9002 Phase2 MPR Project",
            client_name="Client P2",
            location="Mumbai",
            status="active",
            project_start=date(2025, 1, 1),
            contract_finish=date(2026, 6, 30),
            team_lead=self.tl,
        )
        self.project.site_engineers.add(self.tl)
        ProjectDates.objects.create(
            project=self.project,
            date_type=ProjectDates.DATE_TYPE_SCL,
            project_start=date(2025, 1, 1),
            contract_finish=date(2026, 6, 30),
            forecast_finish=date(2026, 8, 15),
        )
        ProjectEOT.objects.create(
            project=self.project,
            eot_number=1,
            extension_days=30,
            original_completion_date=date(2026, 6, 30),
            revised_completion_date=date(2026, 12, 31),
            status=ProjectEOT.STATUS_PENDING,
            reason="Pending",
            is_active=True,
        )
        ProjectEOT.objects.create(
            project=self.project,
            eot_number=2,
            extension_days=45,
            original_completion_date=date(2026, 6, 30),
            revised_completion_date=date(2026, 8, 15),
            approval_date=date(2026, 5, 1),
            status=ProjectEOT.STATUS_APPROVED,
            reason="Approved design",
            is_active=True,
        )
        ConstructionProgress.objects.create(
            projectName=self.project.name,
            progressMonth="2026-07",
            plannedProgress=Decimal("40.00"),
            actualProgress=Decimal("35.00"),
        )
        SiteProgressImage.objects.create(
            project_name=self.project.name,
            month=7,
            year=2026,
            title="Photo 1",
            image_url="https://example.com/p1.jpg",
            cloudinary_public_id="mpr2/p1.jpg",
            storage_backend=SiteProgressImage.STORAGE_S3,
            uploaded_by=self.admin,
        )
        self.month = "2026-07"
        self.generate_url = reverse(
            "mpr-generate", kwargs={"project_id": self.project.id}
        )
        self.history_url = reverse(
            "mpr-history", kwargs={"project_id": self.project.id}
        )

    def _auth(self, user):
        self.client.force_authenticate(user=user)

    def _generate(self, user=None, month=None):
        self._auth(user or self.admin)
        return self.client.post(
            self.generate_url,
            {"month": month or self.month},
            format="json",
        )


class MPRGenerateTests(MPRPhase2Base):
    def test_generate_valid(self):
        resp = self._generate()
        self.assertIn(resp.status_code, (200, 202))
        self.assertTrue(resp.data["success"])
        data = resp.data["data"]
        self.assertEqual(data["status"], MPRReport.STATUS_COMPLETED)
        self.assertTrue(data["pdf_available"])
        self.assertTrue(data["excel_available"])
        report = MPRReport.objects.get(pk=data["id"])
        self.assertIsNotNone(report.snapshot_json)
        self.assertIn("physical_progress", report.snapshot_json)
        self.assertIn("data_availability", report.snapshot_json)

    def test_invalid_month(self):
        self._auth(self.admin)
        resp = self.client.post(self.generate_url, {"month": "bad"}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_invalid_project(self):
        self._auth(self.admin)
        url = reverse("mpr-generate", kwargs={"project_id": 999999})
        resp = self.client.post(url, {"month": self.month}, format="json")
        self.assertEqual(resp.status_code, 404)

    def test_unauthorized(self):
        resp = self._generate(user=self.outsider)
        self.assertEqual(resp.status_code, 403)

    def test_snapshot_immutable_after_source_change(self):
        resp = self._generate()
        report = MPRReport.objects.get(pk=resp.data["data"]["id"])
        snap_progress = report.snapshot_json["physical_progress"]["monthly"][
            "actual_percentage"
        ]
        ConstructionProgress.objects.filter(
            projectName=self.project.name, progressMonth=self.month
        ).update(actualProgress=Decimal("99.00"))
        report.refresh_from_db()
        self.assertEqual(
            report.snapshot_json["physical_progress"]["monthly"]["actual_percentage"],
            snap_progress,
        )

    def test_pending_eot_not_official_in_snapshot(self):
        resp = self._generate()
        snap = MPRReport.objects.get(pk=resp.data["data"]["id"]).snapshot_json
        self.assertEqual(
            snap["time_progress"]["current_completion_date"],
            "2026-08-15",
        )
        self.assertNotEqual(
            snap["time_progress"]["current_completion_date"],
            "2026-12-31",
        )

    def test_duplicate_generate_returns_existing(self):
        r1 = self._generate()
        id1 = r1.data["data"]["id"]
        r2 = self._generate()
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.data["data"]["id"], id1)
        self.assertEqual(
            MPRReport.objects.filter(
                project=self.project, report_year=2026, report_month=7
            ).count(),
            1,
        )

    def test_data_availability_preserved(self):
        resp = self._generate()
        avail = MPRReport.objects.get(pk=resp.data["data"]["id"]).snapshot_json[
            "data_availability"
        ]
        self.assertEqual(avail["weather"]["status"], "unavailable")
        self.assertEqual(avail["formal_vo"]["status"], "unavailable")

    def test_photo_limit_in_snapshot(self):
        for i in range(25):
            SiteProgressImage.objects.create(
                project_name=self.project.name,
                month=7,
                year=2026,
                title=f"P{i}",
                image_url=f"https://example.com/{i}.jpg",
                cloudinary_public_id=f"mpr2/extra{i}.jpg",
                storage_backend=SiteProgressImage.STORAGE_S3,
            )
        resp = self._generate()
        photos = MPRReport.objects.get(pk=resp.data["data"]["id"]).snapshot_json[
            "site_photos"
        ]
        self.assertLessEqual(photos["count"], 20)
        self.assertLessEqual(len(photos["photos"]), 20)

    def test_audit_log_created(self):
        resp = self._generate()
        self.assertTrue(
            BusinessAuditLog.objects.filter(
                entity_type=BusinessAuditLog.ENTITY_MPR,
                entity_id=str(resp.data["data"]["id"]),
            ).exists()
        )


class MPRFilesAndDownloadTests(MPRPhase2Base):
    def test_pdf_and_excel_bytes(self):
        resp = self._generate()
        report = MPRReport.objects.get(pk=resp.data["data"]["id"])
        pdf = render_pdf(report.snapshot_json)
        xlsx = render_excel(report.snapshot_json)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertTrue(xlsx[:2] == b"PK")

    def test_pdf_renderer_no_db_queries(self):
        resp = self._generate()
        snap = MPRReport.objects.get(pk=resp.data["data"]["id"]).snapshot_json
        with CaptureQueriesContext(connection) as ctx:
            render_pdf(snap)
        self.assertEqual(len(ctx), 0)

    def test_excel_renderer_no_db_queries(self):
        resp = self._generate()
        snap = MPRReport.objects.get(pk=resp.data["data"]["id"]).snapshot_json
        with CaptureQueriesContext(connection) as ctx:
            render_excel(snap)
        self.assertEqual(len(ctx), 0)

    def test_download_endpoints(self):
        resp = self._generate()
        mpr_id = resp.data["data"]["id"]
        pdf = self.client.get(reverse("mpr-pdf", kwargs={"mpr_id": mpr_id}))
        excel = self.client.get(reverse("mpr-excel", kwargs={"mpr_id": mpr_id}))
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(excel.status_code, 200)
        self.assertIn("url", pdf.data["data"])
        self.assertIn("url", excel.data["data"])

    def test_detail_and_history(self):
        resp = self._generate()
        mpr_id = resp.data["data"]["id"]
        detail = self.client.get(reverse("mpr-detail", kwargs={"mpr_id": mpr_id}))
        self.assertEqual(detail.status_code, 200)
        self.assertNotIn("snapshot_json", detail.data["data"])
        hist = self.client.get(self.history_url)
        self.assertEqual(hist.status_code, 200)
        self.assertGreaterEqual(hist.data["count"], 1)

    def test_regenerate_creates_new_version(self):
        first = self._generate()
        first_id = first.data["data"]["id"]
        regen = self.client.post(
            reverse("mpr-regenerate", kwargs={"mpr_id": first_id}),
            format="json",
        )
        self.assertEqual(regen.status_code, 202)
        new_id = regen.data["data"]["id"]
        self.assertNotEqual(new_id, first_id)
        old = MPRReport.objects.get(pk=first_id)
        new = MPRReport.objects.get(pk=new_id)
        self.assertFalse(old.is_latest)
        self.assertEqual(old.status, MPRReport.STATUS_ARCHIVED)
        self.assertTrue(new.is_latest)
        self.assertEqual(new.version, 2)
        self.assertEqual(new.status, MPRReport.STATUS_COMPLETED)

    def test_failed_generation_sets_status(self):
        with patch(
            "mpr.services.generation.render_pdf",
            side_effect=RuntimeError("boom"),
        ):
            resp = self._generate(month="2026-06")
        self.assertEqual(resp.status_code, 500)
        self.assertFalse(resp.data["success"])
        report = MPRReport.objects.filter(
            project=self.project, report_year=2026, report_month=6
        ).latest("id")
        self.assertEqual(report.status, MPRReport.STATUS_FAILED)
        self.assertTrue(report.error_message)


class MPRConcurrentGenerateTests(MPRPhase2Base):
    @override_settings(MPR_GENERATION_INLINE=False)
    def test_second_generate_while_generating_returns_same(self):
        # Create generating row without completing job
        from mpr.services.period import parse_mpr_month
        from mpr.services.mpr_service import MPRService

        period = parse_mpr_month(self.month)
        snap = MPRService(self.project, period).build()
        report = MPRReport.objects.create(
            project=self.project,
            report_year=2026,
            report_month=7,
            version=1,
            is_latest=True,
            status=MPRReport.STATUS_GENERATING,
            snapshot_json=snap,
            generated_by=self.admin,
        )
        with patch("mpr.services.generation.submit_mpr_job"):
            resp = self._generate()
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.data["data"]["id"], report.id)
