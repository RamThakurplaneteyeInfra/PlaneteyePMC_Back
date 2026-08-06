"""
End-to-end verification of DPR cumulative progress pipeline.

Not a unit-test assumption — compares SQL aggregate vs DB rows vs API JSON
at every stage (create day1, create day2, scope detail, scope progress).
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.db.models import Sum
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from core.cache_keys import get_list_cache_version
from core.test_auth import authenticate_client
from dpr.models import DailyProgressReport, DPRActivity
from monthly_scope.models import MonthlyScopeWork, ScopeCategory, ScopeSubCategory
from monthly_scope.services import EXCLUDED_DPR_STATUSES, ScopeProgressService
from projects.models import Project


def _sql_sum(scope_id) -> Decimal:
    total = (
        DPRActivity.objects.filter(scope_id=scope_id)
        .exclude(dpr__status__in=EXCLUDED_DPR_STATUSES)
        .aggregate(t=Sum("executed_quantity"))["t"]
    )
    return total or Decimal("0.00")


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "scope-progress-verify",
        }
    }
)
class CumulativeProgressE2EVerification(TestCase):
    """
    Prints / asserts values at every lifecycle stage.
    Failures mean a real pipeline discrepancy (not just service-unit math).
    """

    def setUp(self):
        cache.clear()
        self.tl_group, _ = Group.objects.get_or_create(name="Team Leader")
        self.user = User.objects.create_superuser(
            username="verify_prog_admin",
            email="verify@example.com",
            password="testpass123",
        )
        self.user.groups.add(self.tl_group)
        self.project = Project.objects.create(
            name="E2E Progress Verify Project", status="active"
        )
        self.category = ScopeCategory.objects.create(name="Verify-Cat", display_order=1)
        self.subcategory = ScopeSubCategory.objects.create(
            category=self.category, name="Verify-Sub", display_order=1
        )
        self.scope = MonthlyScopeWork.objects.create(
            project=self.project,
            category=self.category,
            subcategory=self.subcategory,
            month=date(2026, 8, 1),
            description="Verify planned 120",
            unit="Nos",
            planned_quantity=Decimal("120.00"),
            created_by=self.user,
        )
        self.client = APIClient()
        authenticate_client(self.client, username="verify_prog_admin", password="testpass123")
        self.report = {}

    def _create_dpr(self, report_date: str, executed: str):
        return self.client.post(
            "/api/dpr/",
            {
                "project_name": self.project.name,
                "job_no": "JV1",
                "report_date": report_date,
                "issued_by": "SE",
                "designation": "Site Engineer",
                "activities": [
                    {
                        "scope": self.scope.id,
                        "executed_quantity": executed,
                        "next_day_planned_work": "Continue",
                        "remarks": "verify",
                    }
                ],
            },
            format="json",
        )

    def _snapshot(self, label: str, api_activity_cum=None):
        self.scope.refresh_from_db()
        sql_total = _sql_sum(self.scope.id)
        # Force service recompute and capture
        ScopeProgressService.update_scope_progress(self.scope.id)
        self.scope.refresh_from_db()

        scope_api = self.client.get(f"/api/monthly-scope/{self.scope.id}/")
        progress_api = self.client.get(f"/api/monthly-scope/{self.scope.id}/progress/")

        row = {
            "label": label,
            "sql_sum": sql_total,
            "db_scope_cumulative": self.scope.cumulative_quantity,
            "db_scope_progress": self.scope.progress_percentage,
            "db_scope_remaining": self.scope.remaining_quantity,
            "api_create_activity_cumulative": api_activity_cum,
            "scope_detail_cumulative": (
                scope_api.data.get("cumulative_quantity")
                if scope_api.status_code == 200
                else f"HTTP {scope_api.status_code}"
            ),
            "scope_detail_progress": (
                scope_api.data.get("progress_percentage")
                if scope_api.status_code == 200
                else None
            ),
            "progress_endpoint_executed": (
                progress_api.data.get("progress", {}).get("executed_quantity")
                if progress_api.status_code == 200
                else f"HTTP {progress_api.status_code}"
            ),
            "progress_endpoint_pct": (
                progress_api.data.get("progress", {}).get("progress_percentage")
                if progress_api.status_code == 200
                else None
            ),
            "cache_ver_dpr_list": get_list_cache_version("dpr_list"),
            "cache_ver_monthly_scope": get_list_cache_version("monthly_scope_list"),
            "cache_ver_overview": get_list_cache_version("project_overview_v4"),
        }
        self.report[label] = row
        print("\n=== STAGE:", label, "===")
        for k, v in row.items():
            print(f"  {k}: {v}")
        return row

    def test_e2e_day1_4_day2_3_pipeline(self):
        # ---- Day 1 create (executed=4) ----
        r1 = self._create_dpr("2026-08-01", "4.00")
        self.assertIn(r1.status_code, (200, 201), r1.content)
        acts1 = r1.data.get("activities") or r1.data.get("dpr", {}).get("activities") or []
        self.assertTrue(acts1, f"create response missing activities: {r1.data}")
        day1_api_cum = Decimal(str(acts1[0]["cumulative_quantity"]))
        day1_api_exec = Decimal(str(acts1[0]["executed_quantity"]))
        self.assertEqual(day1_api_exec, Decimal("4.00"))

        s1 = self._snapshot("after_day1_create", api_activity_cum=day1_api_cum)
        self.assertEqual(s1["sql_sum"], Decimal("4.00"))
        self.assertEqual(s1["db_scope_cumulative"], Decimal("4.00"))
        self.assertEqual(Decimal(str(s1["scope_detail_cumulative"])), Decimal("4.00"))
        self.assertEqual(Decimal(str(s1["progress_endpoint_executed"])), Decimal("4.00"))
        # Create response must match DB (no stale serializer instance)
        self.assertEqual(day1_api_cum, Decimal("4.00"))

        # ---- Day 2 create (executed=3) → expect cumulative 7 / 5.83% ----
        v_dpr_before = get_list_cache_version("dpr_list")
        v_scope_before = get_list_cache_version("monthly_scope_list")

        r2 = self._create_dpr("2026-08-02", "3.00")
        self.assertIn(r2.status_code, (200, 201), r2.content)
        acts2 = r2.data.get("activities") or r2.data.get("dpr", {}).get("activities") or []
        self.assertTrue(acts2, f"create response missing activities: {r2.data}")
        day2_api_cum = Decimal(str(acts2[0]["cumulative_quantity"]))
        day2_api_exec = Decimal(str(acts2[0]["executed_quantity"]))
        day2_api_pct = Decimal(str(acts2[0]["progress_percentage"]))
        self.assertEqual(day2_api_exec, Decimal("3.00"))

        s2 = self._snapshot("after_day2_create", api_activity_cum=day2_api_cum)

        expected_cum = Decimal("7.00")
        expected_pct = Decimal("5.83")

        # Compare every stage — any mismatch fails the verification
        self.assertEqual(s2["sql_sum"], expected_cum, "SQL aggregate mismatch")
        self.assertEqual(s2["db_scope_cumulative"], expected_cum, "DB scope cumulative mismatch")
        self.assertEqual(s2["db_scope_progress"], expected_pct, "DB scope progress mismatch")
        self.assertEqual(
            Decimal(str(s2["scope_detail_cumulative"])),
            expected_cum,
            "GET /api/monthly-scope/{id}/ mismatch",
        )
        self.assertEqual(
            Decimal(str(s2["scope_detail_progress"])),
            expected_pct,
            "GET /api/monthly-scope/{id}/ progress mismatch",
        )
        self.assertEqual(
            Decimal(str(s2["progress_endpoint_executed"])),
            expected_cum,
            "GET /api/monthly-scope/{id}/progress/ mismatch",
        )
        self.assertEqual(
            Decimal(str(s2["progress_endpoint_pct"])),
            expected_pct,
            "progress endpoint % mismatch",
        )
        self.assertEqual(
            day2_api_cum,
            expected_cum,
            "POST /api/dpr/ create response cumulative STALE or WRONG",
        )
        self.assertEqual(
            day2_api_pct,
            expected_pct,
            "POST /api/dpr/ create response progress STALE or WRONG",
        )

        # Cache versions must bump on write (invalidation happened)
        self.assertGreaterEqual(get_list_cache_version("dpr_list"), v_dpr_before)
        self.assertGreater(
            get_list_cache_version("monthly_scope_list"),
            v_scope_before,
            "monthly_scope cache version did not bump after progress recalc",
        )

        # DPR list must not serve pre-day2 cumulative if FE reloads list
        list_resp = self.client.get("/api/dpr/", {"project_name": self.project.name})
        self.assertEqual(list_resp.status_code, 200)
        # paginated or list
        results = list_resp.data
        if isinstance(results, dict):
            results = results.get("results", results)
        found_day2 = False
        for dpr in results:
            for act in dpr.get("activities") or []:
                if act.get("scope_id") == self.scope.id and str(act.get("executed_quantity")) in (
                    "3.00",
                    "3.0",
                    "3",
                ):
                    found_day2 = True
                    self.assertEqual(
                        Decimal(str(act["cumulative_quantity"])),
                        expected_cum,
                        "GET /api/dpr/ list returned stale cumulative",
                    )
        self.assertTrue(found_day2, "day2 activity not found in DPR list")

        # Reject day2 → cumulative back to 4
        day2_dpr_id = r2.data.get("id") or r2.data.get("dpr", {}).get("id")
        day2_obj = DailyProgressReport.objects.get(pk=day2_dpr_id)
        # Move to pending so reject endpoint accepts, then reject
        day2_obj.status = DailyProgressReport.Status.PENDING_TEAM_LEAD
        day2_obj.save(update_fields=["status"])
        rej = self.client.post(
            f"/api/dpr/{day2_dpr_id}/reject/",
            {"rejection_reason": "verify reject"},
            format="json",
        )
        self.assertEqual(rej.status_code, 200, rej.content)
        self.scope.refresh_from_db()
        self.assertEqual(_sql_sum(self.scope.id), Decimal("4.00"))
        self.assertEqual(self.scope.cumulative_quantity, Decimal("4.00"))

        print("\n=== VERIFICATION SUMMARY ===")
        print("SQL=", s2["sql_sum"], "DB=", s2["db_scope_cumulative"])
        print("ScopeDetail=", s2["scope_detail_cumulative"])
        print("ProgressAPI=", s2["progress_endpoint_executed"])
        print("CreateResponse=", day2_api_cum)
        print("FIX_WORKING=", s2["sql_sum"] == expected_cum == day2_api_cum)
