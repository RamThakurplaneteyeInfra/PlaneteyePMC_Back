"""Tests for GET /api/projects/overview/."""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework import status
from rest_framework.test import APITestCase

from bottlenecks.models import Bottleneck
from construction_progress.models.construction_progress import ConstructionProgress
from core.cache_keys import get_list_cache_version
from core.test_auth import authenticate_client
from cost_performance.models import ProjectCostPerformance
from dpr.models import DailyProgressReport
from health_safety.models import HSERecord
from project_dates.eot_models import ProjectEOT
from project_dates.models import ProjectDates
from project_quality_status.models.project_quality_status import ProjectQualityStatus
from projects.models import Project
from projects.overview_thresholds import (
    STATUS_AT_RISK,
    STATUS_COMPLETED,
    STATUS_CRITICAL,
    STATUS_NO_DATA,
    STATUS_ON_TRACK,
    STATUS_WATCH,
)
from projects.serializers_overview import ProjectOverviewSerializer
from projects.services.overview_kpis import (
    CARD_DELAY,
    CARD_EXCELLENT,
    CARD_NO_DATA,
    build_safety_kpi,
    compute_health_score,
    compute_project_status,
    extract_project_code,
)
from projects.services.project_overview import (
    CACHE_PREFIX,
    ProjectOverviewService,
    invalidate_project_overview_cache,
)


class OverviewKpiHelpersTest(TestCase):
    def test_extract_project_code(self):
        self.assertEqual(extract_project_code("B3482 RGSL: Rajeev Gandhi Sea Link"), "B3482")
        self.assertEqual(
            extract_project_code("KHB Multiplex, Kengeri (A-3462)"), "A-3462"
        )
        self.assertEqual(extract_project_code("Miyapur Flyover"), "")

    def test_health_score_weighted(self):
        # 49*0.25 + 49*0.25 + 68*0.20 + 100*0.20 + 83*0.10 = 66.4 → 66
        self.assertEqual(compute_health_score(49, 49, 83, 68, 100), 66)

    def test_safety_no_hse_is_zero_no_data(self):
        self.assertEqual(
            build_safety_kpi(None),
            {"percentage": 0, "status": CARD_NO_DATA},
        )

    def test_project_status_completed(self):
        project = Project(status="completed")
        self.assertEqual(compute_project_status(project), STATUS_COMPLETED)

    def test_project_status_on_track(self):
        project = Project(status="active")
        finish = date.today() + timedelta(days=90)
        self.assertEqual(
            compute_project_status(project, contract_finish=finish),
            STATUS_ON_TRACK,
        )

    def test_project_status_at_risk_approaching(self):
        project = Project(status="active")
        finish = date.today() + timedelta(days=10)
        self.assertEqual(
            compute_project_status(project, contract_finish=finish),
            STATUS_AT_RISK,
        )

    def test_project_status_watch_minor_delay(self):
        project = Project(status="active")
        finish = date.today() - timedelta(days=5)
        self.assertEqual(
            compute_project_status(project, contract_finish=finish),
            STATUS_WATCH,
        )

    def test_project_status_critical_past_threshold(self):
        project = Project(status="active")
        finish = date.today() - timedelta(days=20)
        self.assertEqual(
            compute_project_status(project, contract_finish=finish),
            STATUS_CRITICAL,
        )

    def test_project_status_prefers_approved_eot(self):
        project = Project(status="active")
        # Contract finish expired, but approved EOT still ahead → On Track
        self.assertEqual(
            compute_project_status(
                project,
                latest_eot_date=date.today() + timedelta(days=60),
                contract_finish=date.today() - timedelta(days=30),
            ),
            STATUS_ON_TRACK,
        )

    def test_project_status_no_dates(self):
        project = Project(status="active")
        self.assertEqual(compute_project_status(project), STATUS_NO_DATA)


class ProjectOverviewAPITest(APITestCase):
    URL = "/api/projects/overview/"

    def setUp(self):
        self.ho_group, _ = Group.objects.get_or_create(name="Head Office")
        self.tl_group, _ = Group.objects.get_or_create(name="Team Leader")
        self.se_group, _ = Group.objects.get_or_create(name="Site Engineer")

        self.ho = User.objects.create_user(username="ov_ho", password="Project@123")
        self.ho.groups.add(self.ho_group)
        self.tl = User.objects.create_user(
            username="ov_tl",
            password="Project@123",
            first_name="Overview",
            last_name="Lead",
        )
        self.tl.groups.add(self.tl_group)
        self.se = User.objects.create_user(username="ov_se", password="Project@123")
        self.se.groups.add(self.se_group)

        self.p1 = Project.objects.create(
            name="B3482 Overview Alpha",
            status="active",
            client_name="GSIDC",
            location="Goa",
            team_lead=self.tl,
            project_start=date.today() - timedelta(days=100),
            contract_finish=date.today() + timedelta(days=100),
        )
        self.p2 = Project.objects.create(
            name="Overview Beta Site",
            status="active",
            client_name="MMRCL",
            location="Mumbai",
            team_lead=self.tl,
        )
        self.p3 = Project.objects.create(
            name="Overview Gamma Planning",
            status="planning",
            client_name="GHMC",
            location="Hyderabad",
        )
        self.merged = Project.objects.create(
            name="Overview Merged Hidden",
            status="merged",
            client_name="X",
        )
        self.other = Project.objects.create(
            name="Unassigned Other Project",
            status="active",
            client_name="Other",
        )

        ConstructionProgress.objects.create(
            projectName=self.p1.name,
            progressMonth="2026-06",
            plannedProgress=80.0,
            actualProgress=49.0,
        )
        ProjectCostPerformance.objects.create(
            project=self.p1,
            project_name=self.p1.name,
            month_year="Jun-2026",
            bcws=Decimal("100"),
            bcwp=Decimal("83"),
            acwp=Decimal("100"),
            fcst=Decimal("20"),
        )
        ProjectQualityStatus.objects.create(
            projectName=self.p1.name,
            month=6,
            year=2026,
            tests_required=100,
            tests_conducted=100,
            tests_passed=68,
            tests_failed=32,
        )
        HSERecord.objects.create(
            projectName=self.p1.name,
            fatalities=0,
            significant=0,
            major=0,
            minor=0,
            nearMiss=0,
            totalManhours=Decimal("10000"),
        )
        Bottleneck.objects.create(
            project=self.p1,
            type=Bottleneck.TYPE_ISSUE,
            description="Issue one",
            priority=Bottleneck.PRIORITY_MEDIUM,
            status=Bottleneck.STATUS_OPEN,
            created_by=self.ho,
        )
        Bottleneck.objects.create(
            project=self.p1,
            type=Bottleneck.TYPE_CONCERN,
            description="Concern not counted as issue",
            priority=Bottleneck.PRIORITY_LOW,
            status=Bottleneck.STATUS_OPEN,
            created_by=self.ho,
        )
        DailyProgressReport.objects.create(
            project_name=self.p1.name,
            job_no="JOB-001",
            report_date=date.today(),
            issued_by="Test Issuer",
            designation="SE",
            created_by=self.ho,
        )

        authenticate_client(self.client, username="ov_ho", password="Project@123")

    def test_schema_and_success_envelope(self):
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(response.data["success"])
        self.assertIn("Project overview", response.data["message"])
        self.assertIsInstance(response.data["data"], list)
        self.assertGreaterEqual(response.data["count"], 3)

        card = next(c for c in response.data["data"] if c["project_id"] == self.p1.id)
        expected_keys = {
            "project_id",
            "project_name",
            "project_code",
            "client",
            "project_type",
            "project_icon",
            "status",
            "project_status",
            "completed_at",
            "completed_by",
            "health_score",
            "progress",
            "time",
            "cost",
            "quality",
            "safety",
            "team_leader",
            "location",
            "issues_count",
            "dpr_count",
            "last_updated",
            "compare_enabled",
        }
        self.assertEqual(set(card.keys()), expected_keys)
        self.assertEqual(card["status"], "active")
        self.assertEqual(card["project_status"], STATUS_ON_TRACK)
        self.assertIsNone(card["completed_at"])
        self.assertIsNone(card["completed_by"])
        self.assertEqual(card["project_code"], "B3482")
        self.assertEqual(card["client"], "GSIDC")
        self.assertEqual(card["progress"]["percentage"], 49)
        self.assertEqual(card["progress"]["status"], CARD_DELAY)
        self.assertEqual(card["cost"]["percentage"], 83)
        self.assertEqual(card["quality"]["percentage"], 68)
        self.assertEqual(card["safety"]["status"], CARD_EXCELLENT)
        self.assertGreater(card["safety"]["percentage"], 0)
        self.assertEqual(card["issues_count"], 1)
        self.assertEqual(card["dpr_count"], 1)
        self.assertEqual(card["team_leader"]["username"], "ov_tl")
        self.assertTrue(card["compare_enabled"])
        # Heavy payloads must not appear
        for banned in ("cashflow", "equipment", "budget", "charts", "notifications"):
            self.assertNotIn(banned, card)

        # Project with no HSE / cost / quality → No Data, never fake 100% safety
        beta = next(c for c in response.data["data"] if c["project_id"] == self.p2.id)
        self.assertEqual(beta["safety"]["percentage"], 0)
        self.assertEqual(beta["safety"]["status"], CARD_NO_DATA)
        self.assertEqual(beta["project_status"], STATUS_NO_DATA)

    def test_serializer_validates_card(self):
        service = ProjectOverviewService(Project.objects.filter(id=self.p1.id))
        payload = service.get_paginated_overview(use_cache=False)
        serializer = ProjectOverviewSerializer(data=payload["data"], many=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_completed_project_status(self):
        completed = Project.objects.create(
            name="Overview Completed KPI",
            status="completed",
            client_name="X",
            project_start=date.today() - timedelta(days=200),
            contract_finish=date.today() - timedelta(days=10),
        )
        response = self.client.get(self.URL)
        card = next(c for c in response.data["data"] if c["project_id"] == completed.id)
        self.assertEqual(card["project_status"], STATUS_COMPLETED)

    def test_approved_eot_drives_time_and_status(self):
        ProjectDates.objects.create(
            project=self.p1,
            date_type=ProjectDates.DATE_TYPE_SCL,
            project_start=date.today() - timedelta(days=100),
            contract_finish=date.today() - timedelta(days=30),
            forecast_finish=date.today() - timedelta(days=20),
        )
        ProjectEOT.objects.create(
            project=self.p1,
            eot_number=1,
            extension_days=90,
            original_completion_date=date.today() - timedelta(days=30),
            revised_completion_date=date.today() + timedelta(days=60),
            approval_date=date.today() - timedelta(days=20),
            reason="Weather",
            status=ProjectEOT.STATUS_APPROVED,
            is_active=True,
            created_by=self.ho,
        )
        service = ProjectOverviewService(Project.objects.filter(id=self.p1.id))
        card = service.get_paginated_overview(use_cache=False)["data"][0]
        self.assertEqual(card["project_status"], STATUS_ON_TRACK)
        self.assertIn(
            card["time"]["status"],
            (STATUS_ON_TRACK, STATUS_WATCH, STATUS_AT_RISK),
        )

    def test_expired_eot_is_critical_or_watch(self):
        ProjectEOT.objects.create(
            project=self.p1,
            eot_number=1,
            extension_days=10,
            original_completion_date=date.today() - timedelta(days=40),
            revised_completion_date=date.today() - timedelta(days=20),
            approval_date=date.today() - timedelta(days=35),
            reason="Delay",
            status=ProjectEOT.STATUS_APPROVED,
            is_active=True,
            created_by=self.ho,
        )
        service = ProjectOverviewService(Project.objects.filter(id=self.p1.id))
        card = service.get_paginated_overview(use_cache=False)["data"][0]
        self.assertEqual(card["project_status"], STATUS_CRITICAL)

    def test_cache_invalidation_on_hse_and_eot(self):
        v_before = get_list_cache_version(CACHE_PREFIX)
        HSERecord.objects.create(
            projectName=self.p2.name,
            fatalities=0,
            significant=0,
            major=0,
            minor=1,
            nearMiss=0,
            totalManhours=Decimal("5000"),
        )
        self.assertGreater(get_list_cache_version(CACHE_PREFIX), v_before)

        v2 = get_list_cache_version(CACHE_PREFIX)
        ProjectEOT.objects.create(
            project=self.p2,
            eot_number=1,
            extension_days=5,
            original_completion_date=date.today(),
            revised_completion_date=date.today() + timedelta(days=5),
            approval_date=date.today(),
            reason="Test",
            status=ProjectEOT.STATUS_APPROVED,
            is_active=True,
            created_by=self.ho,
        )
        self.assertGreater(get_list_cache_version(CACHE_PREFIX), v2)

        invalidate_project_overview_cache()
        self.assertGreaterEqual(get_list_cache_version(CACHE_PREFIX), v2)

    def test_rbac_team_leader_only_assigned(self):
        authenticate_client(self.client, username="ov_tl", password="Project@123")
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {c["project_id"] for c in response.data["data"]}
        self.assertIn(self.p1.id, ids)
        self.assertIn(self.p2.id, ids)
        self.assertNotIn(self.other.id, ids)
        self.assertNotIn(self.merged.id, ids)

    def test_rbac_site_engineer_assigned(self):
        self.p1.site_engineers.add(self.se)
        self.p1.site_engineer = self.se
        self.p1.save(update_fields=["site_engineer", "updated_at"])
        authenticate_client(self.client, username="ov_se", password="Project@123")
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {c["project_id"] for c in response.data["data"]}
        self.assertEqual(ids, {self.p1.id})

    def test_default_returns_all_without_pagination(self):
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertNotIn("page", response.data)
        self.assertNotIn("page_size", response.data)
        self.assertNotIn("total_pages", response.data)
        self.assertEqual(response.data["count"], len(response.data["data"]))
        ids = {c["project_id"] for c in response.data["data"]}
        self.assertIn(self.p1.id, ids)
        self.assertIn(self.p2.id, ids)
        self.assertIn(self.other.id, ids)
        # Planning / merged must not appear on default dashboard cards
        self.assertNotIn(self.p3.id, ids)
        self.assertNotIn(self.merged.id, ids)

    def test_optional_pagination(self):
        response = self.client.get(
            self.URL, {"paginate": "true", "page": 1, "page_size": 2}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["page"], 1)
        self.assertEqual(response.data["page_size"], 2)
        self.assertEqual(len(response.data["data"]), 2)
        self.assertGreaterEqual(response.data["count"], 3)
        self.assertIn("total_pages", response.data)

        page2 = self.client.get(
            self.URL, {"paginate": "true", "page": 2, "page_size": 2}
        )
        self.assertEqual(page2.status_code, status.HTTP_200_OK)
        ids_p1 = {c["project_id"] for c in response.data["data"]}
        ids_p2 = {c["project_id"] for c in page2.data["data"]}
        self.assertTrue(ids_p1.isdisjoint(ids_p2) or page2.data["count"] <= 2)

    def test_page_params_ignored_without_paginate_flag(self):
        response = self.client.get(self.URL, {"page": 1, "page_size": 1})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("page", response.data)
        self.assertGreaterEqual(len(response.data["data"]), 3)

    def test_search_and_client_filter(self):
        response = self.client.get(self.URL, {"search": "Alpha"})
        names = [c["project_name"] for c in response.data["data"]]
        self.assertTrue(all("Alpha" in n for n in names))

        response = self.client.get(self.URL, {"client": "MMRCL"})
        clients = {c["client"] for c in response.data["data"]}
        self.assertEqual(clients, {"MMRCL"})

    def test_default_excludes_planning_merged_includes_completed(self):
        completed = Project.objects.create(
            name="Overview Completed Visible", status="completed", client_name="X"
        )
        response = self.client.get(self.URL)
        ids = {c["project_id"] for c in response.data["data"]}
        self.assertNotIn(self.p3.id, ids)
        self.assertNotIn(self.merged.id, ids)
        self.assertIn(completed.id, ids)
        for card in response.data["data"]:
            self.assertIn(
                Project.objects.get(id=card["project_id"]).status,
                {"active", "completed"},
            )
            self.assertIn("status", card)

    def test_explicit_planning_status_still_works(self):
        response = self.client.get(self.URL, {"status": "planning"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {c["project_id"] for c in response.data["data"]}
        self.assertIn(self.p3.id, ids)
        self.assertNotIn(self.merged.id, ids)

    def test_status_filter_excludes_merged_by_default(self):
        response = self.client.get(self.URL, {"status": "active"})
        statuses_ok = all(
            Project.objects.get(id=c["project_id"]).status == "active"
            for c in response.data["data"]
        )
        self.assertTrue(statuses_ok)
        ids = {c["project_id"] for c in response.data["data"]}
        self.assertNotIn(self.merged.id, ids)
        self.assertNotIn(self.p3.id, ids)

    def test_sorting_by_health_score(self):
        response = self.client.get(self.URL, {"ordering": "-health_score"})
        scores = [c["health_score"] for c in response.data["data"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_query_count_bounded_for_many_projects(self):
        # Seed additional projects so list is large but KPIs still bulk-fetched.
        Project.objects.bulk_create(
            [
                Project(name=f"Overview Bulk {i:03d}", status="active", client_name="Bulk")
                for i in range(60)
            ]
        )
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(self.URL, {"status": "active"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(response.data["count"], 60)
        self.assertEqual(response.data["count"], len(response.data["data"]))
        # RBAC + project list + bulk KPI maps should stay well under N*projects.
        self.assertLess(len(ctx.captured_queries), 35)

    def test_large_dataset_service_builds_without_n_plus_one(self):
        projects = Project.objects.bulk_create(
            [
                Project(name=f"Scale Project {i:04d}", status="active", client_name="Scale")
                for i in range(120)
            ]
        )
        # Attach sparse KPI rows
        ConstructionProgress.objects.bulk_create(
            [
                ConstructionProgress(
                    projectName=p.name,
                    progressMonth="2026-05",
                    plannedProgress=50,
                    actualProgress=40,
                )
                for p in projects[:40]
            ]
        )
        qs = Project.objects.filter(name__startswith="Scale Project")
        service = ProjectOverviewService(qs)
        with CaptureQueriesContext(connection) as ctx:
            payload = service.get_paginated_overview(use_cache=False)
        self.assertEqual(len(payload["data"]), 120)
        self.assertEqual(payload["count"], 120)
        self.assertNotIn("page", payload)
        self.assertLess(len(ctx.captured_queries), 20)

        paginated = service.get_paginated_overview(
            paginate=True, page=1, page_size=50, use_cache=False
        )
        self.assertEqual(len(paginated["data"]), 50)
        self.assertEqual(paginated["count"], 120)
        self.assertEqual(paginated["page"], 1)
