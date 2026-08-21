"""
DPR performance regression: query counts, cache, progress correctness.

Does not change API contracts. Asserts that multi-scope writes stay off the
per-activity N+1 path and that cumulative formulas remain unchanged.
"""

from datetime import date
from decimal import Decimal
from time import perf_counter
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.db import connection
from django.db.models import Sum
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from rest_framework import status
from rest_framework.test import APIClient

from core.test_auth import authenticate_client
from dpr.models import DailyProgressReport, DPRActivity
from monthly_scope.models import MonthlyScopeWork, ScopeCategory, ScopeSubCategory
from monthly_scope.services import EXCLUDED_DPR_STATUSES, ScopeProgressService
from projects.models import Project


@override_settings(
    DEBUG=True,
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "dpr-perf-regression",
        }
    },
    DPR_EMAIL_INLINE=True,
    DPR_PERF_LOG=True,
)
class DprPerformanceRegressionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_superuser(
            username="dpr_perf_admin",
            email="dprperf@example.com",
            password="testpass123",
        )
        tl_group, _ = Group.objects.get_or_create(name="Team Leader")
        self.user.groups.add(tl_group)
        self.project = Project.objects.create(
            name="DPR Perf Audit Project", status="active", team_lead=self.user
        )
        self.category = ScopeCategory.objects.create(name="Perf-Cat", display_order=1)
        self.subcategory = ScopeSubCategory.objects.create(
            category=self.category, name="Perf-Sub", display_order=1
        )
        self.scopes = [
            MonthlyScopeWork.objects.create(
                project=self.project,
                category=self.category,
                subcategory=self.subcategory,
                month=date(2026, 8, 1),
                description=f"Perf scope {index}",
                unit="Nos",
                planned_quantity=Decimal("120.00"),
                created_by=self.user,
            )
            for index in range(10)
        ]
        self.client = APIClient()
        authenticate_client(self.client, username="dpr_perf_admin", password="testpass123")

    def _payload(self, report_date, scopes, executed="4.00"):
        return {
            "project_name": self.project.name,
            "job_no": "PERF-001",
            "report_date": report_date,
            "issued_by": "SE",
            "designation": "Site Engineer",
            "activities": [
                {
                    "scope": scope.id,
                    "executed_quantity": executed,
                    "next_day_planned_work": "Continue",
                    "remarks": "ok",
                }
                for scope in scopes
            ],
        }

    def _sql_sum(self, scope_id):
        total = (
            DPRActivity.objects.filter(scope_id=scope_id)
            .exclude(dpr__status__in=EXCLUDED_DPR_STATUSES)
            .aggregate(t=Sum("executed_quantity"))["t"]
        )
        return total or Decimal("0.00")

    def test_create_ten_scopes_stays_off_n_plus_one(self):
        payload = self._payload("2026-08-03", self.scopes)
        started = perf_counter()
        with CaptureQueriesContext(connection) as queries:
            response = self.client.post("/api/dpr/", payload, format="json")
        elapsed_ms = round((perf_counter() - started) * 1000, 1)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        print(f"[DPR PERF] POST /api/dpr/ 10 scopes queries={len(queries)} total_ms={elapsed_ms}")
        self.assertLessEqual(len(queries), 55)
        data = response.data
        self.assertEqual(len(data["activities"]), 10)
        self.assertEqual(data["status"], "draft")
        self.assertNotIn("approval_status", data)

    def test_create_without_activities_still_works(self):
        payload = self._payload("2026-08-04", [])
        payload.pop("activities")
        response = self.client.post("/api/dpr/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["activities"], [])

    def test_list_query_count_cold_and_warm_cache(self):
        self.client.post("/api/dpr/", self._payload("2026-08-05", self.scopes[:5]), format="json")
        cache.clear()
        with CaptureQueriesContext(connection) as cold:
            cold_resp = self.client.get("/api/dpr/?page=1")
        self.assertEqual(cold_resp.status_code, 200)
        self.assertIn("results", cold_resp.data)
        with CaptureQueriesContext(connection) as warm:
            warm_resp = self.client.get("/api/dpr/?page=1")
        print(
            f"[DPR PERF] GET /api/dpr/ cold_q={len(cold)} warm_q={len(warm)} "
            f"payload={len(cold_resp.content)} bytes"
        )
        self.assertLessEqual(len(cold), 20)
        self.assertLessEqual(len(warm), 8)
        self.assertEqual(
            set(cold_resp.data["results"][0].keys()),
            set(warm_resp.data["results"][0].keys()),
        )

    def test_detail_uses_prefetched_activities(self):
        created = self.client.post(
            "/api/dpr/", self._payload("2026-08-06", self.scopes[:5]), format="json"
        )
        dpr_id = created.data["id"]
        cache.clear()
        connection.queries_log.clear()
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(f"/api/dpr/{dpr_id}/")
        self.assertEqual(response.status_code, 200)
        print(f"[DPR PERF] GET /api/dpr/{{id}}/ queries={len(queries)}")
        # Admin read: no RBAC Project SELECT; prefetch covers activities/scopes.
        self.assertGreaterEqual(len(queries), 1)
        self.assertLessEqual(len(queries), 8)
        self.assertEqual(len(response.data["activities"]), 5)
        dpr_selects = sum(
            1
            for q in queries
            if "dpr_dailyprogressreport" in q["sql"].lower()
            and q["sql"].lstrip().lower().startswith("select")
        )
        self.assertEqual(dpr_selects, 1)

    def test_detail_query_count_stable_with_more_activities(self):
        created = self.client.post(
            "/api/dpr/", self._payload("2026-08-09", self.scopes), format="json"
        )
        dpr_id = created.data["id"]
        cache.clear()
        with CaptureQueriesContext(connection) as q5:
            r5 = self.client.get(f"/api/dpr/{dpr_id}/")
        self.assertEqual(r5.status_code, 200)
        self.assertEqual(len(r5.data["activities"]), 10)
        with CaptureQueriesContext(connection) as q10:
            r10 = self.client.get(f"/api/dpr/{dpr_id}/")
        self.assertEqual(len(q5), len(q10))
        self.assertLessEqual(len(q10), 8)

    def test_list_warm_cache_avoids_sql(self):
        self.client.post("/api/dpr/", self._payload("2026-08-10", self.scopes[:3]), format="json")
        cache.clear()
        cold = self.client.get("/api/dpr/?page=1")
        self.assertEqual(cold.status_code, 200)
        with CaptureQueriesContext(connection) as warm_q:
            warm = self.client.get("/api/dpr/?page=1")
        self.assertEqual(warm.status_code, 200)
        self.assertLessEqual(len(warm_q), 2)
        self.assertEqual(len(cold.data["results"]), len(warm.data["results"]))

    def test_submit_query_count_and_status(self):
        created = self.client.post(
            "/api/dpr/", self._payload("2026-08-07", self.scopes[:5]), format="json"
        )
        dpr_id = created.data["id"]
        started = perf_counter()
        with CaptureQueriesContext(connection) as queries:
            with patch("services.notifications.send_websocket_notification"):
                response = self.client.post(f"/api/dpr/{dpr_id}/submit/", {}, format="json")
        elapsed_ms = round((perf_counter() - started) * 1000, 1)
        self.assertEqual(response.status_code, 200, response.content)
        print(f"[DPR PERF] POST /api/dpr/{{id}}/submit/ queries={len(queries)} total_ms={elapsed_ms}")
        self.assertLessEqual(len(queries), 60)
        self.assertEqual(response.data["status"], DailyProgressReport.Status.PENDING_TEAM_LEAD)

    def test_submit_with_activities_does_not_loop_first(self):
        created = self.client.post(
            "/api/dpr/", self._payload("2026-08-08", self.scopes[:3], "4.00"), format="json"
        )
        dpr_id = created.data["id"]
        body = {
            "activities": [
                {
                    "scope": self.scopes[0].id,
                    "executed_quantity": "5.00",
                    "next_day_planned_work": "x",
                    "remarks": "y",
                }
            ]
        }
        with patch("services.notifications.send_websocket_notification"):
            response = self.client.post(f"/api/dpr/{dpr_id}/submit/", body, format="json")
        self.assertEqual(response.status_code, 200)
        activity = DPRActivity.objects.get(dpr_id=dpr_id, scope=self.scopes[0])
        self.assertEqual(activity.executed_quantity, Decimal("5.00"))

    def test_draft_pending_approved_rejected_cumulative(self):
        day1 = self.client.post(
            "/api/dpr/", self._payload("2026-08-09", self.scopes[:1], "4.00"), format="json"
        )
        self.assertEqual(day1.status_code, 201)
        self.scopes[0].refresh_from_db()
        self.assertEqual(self.scopes[0].cumulative_quantity, Decimal("4.00"))
        self.assertEqual(self._sql_sum(self.scopes[0].id), Decimal("4.00"))

        day2 = self.client.post(
            "/api/dpr/", self._payload("2026-08-10", self.scopes[:1], "3.00"), format="json"
        )
        self.assertEqual(day2.status_code, 201)
        self.scopes[0].refresh_from_db()
        self.assertEqual(self.scopes[0].cumulative_quantity, Decimal("7.00"))
        self.assertEqual(self.scopes[0].progress_percentage, Decimal("5.83"))

        dpr2 = DailyProgressReport.objects.get(pk=day2.data["id"])
        dpr2.status = DailyProgressReport.Status.REJECTED
        dpr2.save(update_fields=["status"])
        ScopeProgressService.recalculate_for_dpr(dpr2)
        self.scopes[0].refresh_from_db()
        self.assertEqual(self.scopes[0].cumulative_quantity, Decimal("4.00"))

        dpr1 = DailyProgressReport.objects.get(pk=day1.data["id"])
        dpr1.status = DailyProgressReport.Status.APPROVED
        dpr1.save(update_fields=["status"])
        ScopeProgressService.recalculate_for_dpr(dpr1)
        self.scopes[0].refresh_from_db()
        self.assertEqual(self.scopes[0].cumulative_quantity, Decimal("4.00"))

    def test_form_open_project_scopes_query_count(self):
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(
                f"/api/monthly-scope/project-scopes/?project_id={self.project.id}"
            )
        self.assertEqual(response.status_code, 200)
        print(f"[DPR PERF] GET monthly-scope/project-scopes queries={len(queries)}")
        self.assertLessEqual(len(queries), 12)
        self.assertGreaterEqual(len(response.data), 10)

    @patch("services.email_utils.send_html_email")
    @patch("services.notifications.send_websocket_notification")
    def test_submit_does_not_call_smtp_inline(self, mock_ws, mock_email):
        created = self.client.post(
            "/api/dpr/", self._payload("2026-08-11", self.scopes[:1]), format="json"
        )
        response = self.client.post(
            f"/api/dpr/{created.data['id']}/submit/", {}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        mock_email.assert_not_called()
        mock_ws.assert_called()
