"""MPR preview API tests."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from bottlenecks.models import Bottleneck
from construction_progress.models.construction_progress import ConstructionProgress
from contract_values.models import ContractValue
from correspondence.models.correspondence import CorrespondenceDocument
from cost_performance.models import ProjectCostPerformance
from drawings.models.drawing_register import DrawingRegisterItem
from health_safety.models import HealthSafetyRecord
from manpower.models import ProjectManpower
from monthly_scope.models import MonthlyScopeWork, ScopeCategory, ScopeSubCategory
from project_dates.eot_models import ProjectEOT
from project_dates.models import BGStatus, ProjectDates
from project_equipment.models.project_equipment import ProjectEquipment
from project_quality_status.models.project_quality_status import ProjectQualityStatus
from projects.models import Project
from site_images.models import SiteProgressImage

User = get_user_model()


class MPRPreviewBaseTest(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.admin = User.objects.create_user(
            username="mpr_admin",
            email="mpr_admin@example.com",
            password="pass12345",
            is_staff=True,
            is_superuser=True,
        )
        self.outsider = User.objects.create_user(
            username="mpr_outsider",
            email="mpr_outsider@example.com",
            password="pass12345",
        )
        self.engineer = User.objects.create_user(
            username="mpr_eng",
            email="mpr_eng@example.com",
            password="pass12345",
        )
        self.project = Project.objects.create(
            name="B9001 Test MPR Project",
            client_name="Test Client",
            location="Pune",
            status="active",
            project_start=date(2025, 1, 1),
            contract_finish=date(2026, 6, 30),
            team_lead=self.engineer,
        )
        self.project.site_engineers.add(self.engineer)
        self.month = "2026-07"
        self.url = reverse("mpr-preview", kwargs={"project_id": self.project.id})

    def _auth(self, user):
        self.client.force_authenticate(user=user)


class MPRPreviewValidationTests(MPRPreviewBaseTest):
    def test_missing_month(self):
        self._auth(self.admin)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(resp.data["success"])

    def test_invalid_month(self):
        self._auth(self.admin)
        resp = self.client.get(self.url, {"month": "07-2026"})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_project(self):
        self._auth(self.admin)
        url = reverse("mpr-preview", kwargs={"project_id": 999999})
        resp = self.client.get(url, {"month": self.month})
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_unauthorized_project(self):
        self._auth(self.outsider)
        resp = self.client.get(self.url, {"month": self.month})
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated(self):
        resp = self.client.get(self.url, {"month": self.month})
        self.assertIn(resp.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))


class MPRPreviewDataTests(MPRPreviewBaseTest):
    def setUp(self):
        super().setUp()
        ProjectDates.objects.create(
            project=self.project,
            date_type=ProjectDates.DATE_TYPE_SCL,
            project_start=date(2025, 1, 1),
            contract_finish=date(2026, 6, 30),
            forecast_finish=date(2026, 8, 15),
        )
        # Pending EOT must NOT become official completion
        ProjectEOT.objects.create(
            project=self.project,
            eot_number=1,
            extension_days=30,
            original_completion_date=date(2026, 6, 30),
            revised_completion_date=date(2026, 12, 31),
            status=ProjectEOT.STATUS_PENDING,
            reason="Pending rain",
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
            reason="Design change",
            is_active=True,
        )
        ConstructionProgress.objects.create(
            projectName=self.project.name,
            progressMonth=self.month,
            plannedProgress=Decimal("40.00"),
            actualProgress=Decimal("35.00"),
        )
        cat = ScopeCategory.objects.create(name="Civil")
        sub = ScopeSubCategory.objects.create(category=cat, name="Excavation")
        MonthlyScopeWork.objects.create(
            project=self.project,
            category=cat,
            subcategory=sub,
            month=date(2026, 7, 1),
            planned_quantity=Decimal("100"),
            cumulative_quantity=Decimal("40"),
            unit="cum",
        )
        ProjectCostPerformance.objects.create(
            project=self.project,
            project_name=self.project.name,
            month_year="Jul-2026",
            bcws=Decimal("100"),
            bcwp=Decimal("90"),
            acwp=Decimal("95"),
            fcst=Decimal("50"),
            bac=Decimal("200"),
        )
        ContractValue.objects.create(
            project_name=self.project.name,
            contract_type=ContractValue.ContractType.SCL,
            original_contract_value=Decimal("1000000"),
            excess_value=Decimal("50000"),
            saving=Decimal("10000"),
        )
        CorrespondenceDocument.objects.create(
            project_name=self.project.name,
            month=7,
            year=2026,
            correspondence_type=CorrespondenceDocument.TYPE_CLIENT,
            flow_direction=CorrespondenceDocument.FLOW_INBOUND,
            sr_no=1,
            description="Pending client decision letter",
            delivered_status=CorrespondenceDocument.STATUS_PENDING,
            received_date=date(2026, 7, 5),
            sender="Client",
        )
        DrawingRegisterItem.objects.create(
            project=self.project,
            sr_no=1,
            drawing_name="Foundation Plan",
            revision=1,
            submitted_date=date(2026, 7, 10),
        )
        Bottleneck.objects.create(
            project=self.project,
            type=Bottleneck.TYPE_ACTION,
            description="Client to approve VO",
            priority=Bottleneck.PRIORITY_HIGH,
            status=Bottleneck.STATUS_OPEN,
            target_date=date.today() + timedelta(days=10),
            created_by=self.admin,
        )
        risk = Bottleneck.objects.create(
            project=self.project,
            type=Bottleneck.TYPE_RISK,
            description="Material delay",
            priority=Bottleneck.PRIORITY_CRITICAL,
            status=Bottleneck.STATUS_OPEN,
            target_date=date.today() + timedelta(days=1),
            created_by=self.admin,
        )
        # Force overdue without violating create-time validation
        Bottleneck.objects.filter(pk=risk.pk).update(
            target_date=date.today() - timedelta(days=5)
        )
        ProjectQualityStatus.objects.create(
            projectName=self.project.name,
            month=7,
            year=2026,
            tests_required=10,
            tests_conducted=8,
            tests_passed=7,
            tests_failed=1,
        )
        HealthSafetyRecord.objects.create(
            project_name=self.project.name,
            month=7,
            year=2026,
            fatalities=0,
            significant=0,
            major=0,
            minor=1,
            near_miss=2,
            average_daily_manpower=Decimal("50"),
            working_days=25,
        )
        ProjectManpower.objects.create(
            project_name=self.project.name,
            month_year="Jul-2026",
            planned_manpower=100,
            actual_manpower=90,
            working_hours_per_day=8,
            working_days_per_month=25,
        )
        ProjectEquipment.objects.create(
            projectName=self.project.name,
            equipmentMonth=self.month,
            plannedEquipment=10,
            actualEquipment=8,
        )
        SiteProgressImage.objects.create(
            project_name=self.project.name,
            month=7,
            year=2026,
            title="Tower A",
            image_url="https://pmcproject.s3.ap-south-1.amazonaws.com/site/a.jpg",
            cloudinary_public_id="site/a.jpg",
            storage_backend=SiteProgressImage.STORAGE_S3,
            uploaded_by=self.admin,
        )
        scl = ProjectDates.objects.get(
            project=self.project, date_type=ProjectDates.DATE_TYPE_SCL
        )
        BGStatus.objects.create(
            project_date=scl,
            bg_type=BGStatus.BG_TYPE_SCL,
            bg_name="Performance BG",
            due_date=date(2026, 12, 31),
            updated_date=date(2026, 6, 1),
            remarks="Partial BG fields only",
        )

    def test_valid_preview_structure(self):
        self._auth(self.admin)
        resp = self.client.get(self.url, {"month": self.month})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["success"])
        data = resp.data["data"]
        for key in (
            "project",
            "reporting_period",
            "executive_summary",
            "key_indicators",
            "physical_progress",
            "time_progress",
            "eot",
            "financial_progress",
            "bg",
            "correspondence",
            "drawings",
            "bottlenecks",
            "quality",
            "hse",
            "manpower",
            "equipment",
            "site_photos",
            "achievements",
            "client_decisions",
            "data_availability",
        ):
            self.assertIn(key, data)

        self.assertEqual(data["reporting_period"]["month"], "2026-07")
        self.assertEqual(data["reporting_period"]["start_date"], "2026-07-01")
        self.assertEqual(data["reporting_period"]["end_date"], "2026-07-31")

    def test_physical_progress(self):
        self._auth(self.admin)
        data = self.client.get(self.url, {"month": self.month}).data["data"]
        monthly = data["physical_progress"]["monthly"]
        self.assertEqual(monthly["planned_percentage"], 40.0)
        self.assertEqual(monthly["actual_percentage"], 35.0)
        scope = data["physical_progress"]["scope_progress"]
        self.assertEqual(scope["planned_quantity"], 100.0)
        self.assertEqual(scope["cumulative_quantity"], 40.0)

    def test_eot_pending_not_official(self):
        self._auth(self.admin)
        data = self.client.get(self.url, {"month": self.month}).data["data"]
        eot = data["eot"]
        self.assertEqual(eot["eot_count"], 2)
        self.assertEqual(eot["latest_approved_eot"]["eot_number"], 2)
        self.assertEqual(
            eot["latest_approved_eot"]["revised_completion_date"],
            "2026-08-15",
        )
        self.assertEqual(
            data["time_progress"]["current_completion_date"],
            "2026-08-15",
        )
        # Pending EOT Dec date must not win
        self.assertNotEqual(
            data["time_progress"]["current_completion_date"],
            "2026-12-31",
        )

    def test_financial_and_bg_partial(self):
        self._auth(self.admin)
        data = self.client.get(self.url, {"month": self.month}).data["data"]
        evm = data["financial_progress"]["evm"]
        self.assertIsNotNone(evm)
        self.assertEqual(evm["BCWS"], 100.0)
        self.assertIsNone(evm["SPI"])
        contract = data["financial_progress"]["contract"]
        self.assertEqual(contract["revised_contract_value"], 1040000.0)

        bg = data["bg"]
        self.assertTrue(bg["available"])
        self.assertEqual(len(bg["records"]), 1)
        self.assertIn("BG amount", bg["limitations"][0])
        rec = bg["records"][0]
        self.assertNotIn("amount", rec)
        self.assertNotIn("bg_number", rec)

    def test_correspondence_drawings_bottlenecks(self):
        self._auth(self.admin)
        data = self.client.get(self.url, {"month": self.month}).data["data"]
        self.assertGreaterEqual(data["correspondence"]["summary"]["total_received"], 1)
        self.assertGreaterEqual(data["drawings"]["submitted"], 1)
        self.assertIsNone(data["bottlenecks"]["resolved_count"])
        self.assertGreaterEqual(data["bottlenecks"]["critical_count"], 1)

    def test_quality_hse_manpower_equipment_photos(self):
        self._auth(self.admin)
        data = self.client.get(self.url, {"month": self.month}).data["data"]
        self.assertTrue(data["quality"]["available"])
        self.assertEqual(data["quality"]["tests_passed"], 7)
        self.assertTrue(data["hse"]["available"])
        self.assertEqual(data["hse"]["record"]["near_miss"], 2)
        self.assertTrue(data["manpower"]["available"])
        self.assertEqual(data["manpower"]["actual_headcount"], 90)
        self.assertIsNotNone(data["equipment"]["kpi"])
        self.assertIsNone(data["equipment"]["utilization_percentage"])
        self.assertEqual(data["site_photos"]["count"], 1)
        self.assertTrue(
            data["site_photos"]["photos"][0]["image_url"].startswith("https://")
        )

    def test_data_availability_flags(self):
        self._auth(self.admin)
        avail = self.client.get(self.url, {"month": self.month}).data["data"][
            "data_availability"
        ]
        self.assertEqual(avail["weather"]["status"], "unavailable")
        self.assertEqual(avail["formal_vo"]["status"], "unavailable")
        self.assertEqual(avail["executive_narrative"]["status"], "manual_input_required")
        self.assertEqual(avail["ncr"]["status"], "unavailable")
        self.assertEqual(avail["bg"]["status"], "partial")
        self.assertIn("SPI", avail["evm"]["missing"])

    def test_client_decisions_derived(self):
        self._auth(self.admin)
        items = self.client.get(self.url, {"month": self.month}).data["data"][
            "client_decisions"
        ]["items"]
        sources = {i["source"] for i in items}
        self.assertIn("bottleneck_action", sources)
        self.assertIn("correspondence_pending", sources)

    def test_empty_month_still_returns_envelope(self):
        self._auth(self.admin)
        resp = self.client.get(self.url, {"month": "2024-01"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.data["data"]
        self.assertEqual(data["reporting_period"]["month"], "2024-01")
        self.assertIsNone(data["physical_progress"]["monthly"]["actual_percentage"])

    def test_rbac_assigned_engineer(self):
        self._auth(self.engineer)
        resp = self.client.get(self.url, {"month": self.month})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_executive_summary_no_ai_narrative(self):
        self._auth(self.admin)
        exe = self.client.get(self.url, {"month": self.month}).data["data"][
            "executive_summary"
        ]
        self.assertTrue(exe["manual_input_required"])
        self.assertIsNone(exe["executive_summary"])
        self.assertIn("auto", exe)


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "mpr-tests",
        }
    }
)
class MPRCacheTests(MPRPreviewBaseTest):
    def test_cache_hit_and_invalidation(self):
        self._auth(self.admin)
        r1 = self.client.get(self.url, {"month": self.month})
        self.assertEqual(r1.data.get("meta", {}).get("cache"), "miss")
        r2 = self.client.get(self.url, {"month": self.month})
        self.assertEqual(r2.data.get("meta", {}).get("cache"), "hit")

        # Source change invalidates via signal
        ConstructionProgress.objects.create(
            projectName=self.project.name,
            progressMonth=self.month,
            plannedProgress=Decimal("50.00"),
            actualProgress=Decimal("45.00"),
        )
        r3 = self.client.get(self.url, {"month": self.month})
        self.assertEqual(r3.data.get("meta", {}).get("cache"), "miss")


class MPRQueryCountTests(MPRPreviewBaseTest):
    def test_query_count_bounded(self):
        self._auth(self.admin)
        # Seed several photos / bottlenecks
        for i in range(15):
            SiteProgressImage.objects.create(
                project_name=self.project.name,
                month=7,
                year=2026,
                title=f"Photo {i}",
                image_url=f"https://example.com/{i}.jpg",
                cloudinary_public_id=f"site/p{i}.jpg",
                storage_backend=SiteProgressImage.STORAGE_S3,
            )
            Bottleneck.objects.create(
                project=self.project,
                type=Bottleneck.TYPE_ISSUE,
                description=f"Issue {i}",
                priority=Bottleneck.PRIORITY_LOW,
                status=Bottleneck.STATUS_OPEN,
                created_by=self.admin,
            )

        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            resp = self.client.get(self.url, {"month": self.month})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        # Bound: aggregation should stay well below N+1 (15 photos + 15 bottlenecks)
        self.assertLess(len(ctx), 80)
