"""
Regression tests: Assigned Scope progress must use CUMULATIVE executed qty.

Progress = SUM(valid DPR executed_quantity) / planned_quantity * 100
"""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from dpr.models import DailyProgressReport, DPRActivity
from monthly_scope.models import MonthlyScopeWork, ScopeCategory, ScopeSubCategory
from monthly_scope.services import ScopeProgressService
from projects.models import Project


class CumulativeScopeProgressTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="prog_se", password="testpass123")
        self.project = Project.objects.create(name="Progress Cumul Project", status="active")
        self.category = ScopeCategory.objects.create(name="Civil-Prog", display_order=1)
        self.subcategory = ScopeSubCategory.objects.create(
            category=self.category, name="Excavation-Prog", display_order=1
        )
        self.scope = MonthlyScopeWork.objects.create(
            project=self.project,
            category=self.category,
            subcategory=self.subcategory,
            month=date(2026, 8, 1),
            description="Planned 120 Nos",
            unit="Nos",
            planned_quantity=Decimal("120.00"),
            status="pending",
            created_by=self.user,
        )

    def _make_dpr(self, day_offset: int, status: str, executed: str) -> DPRActivity:
        dpr = DailyProgressReport.objects.create(
            project_name=self.project.name,
            job_no="J-PROG",
            report_date=date(2026, 8, 1) + timedelta(days=day_offset),
            issued_by="SE",
            designation="Site Engineer",
            status=status,
            submitted_by=self.user,
            created_by=self.user,
        )
        return DPRActivity.objects.create(
            dpr=dpr,
            scope=self.scope,
            executed_quantity=Decimal(executed),
        )

    def test_case1_day1_then_day2_cumulative(self):
        # Day1 = 3 → 2.50%
        self._make_dpr(0, DailyProgressReport.Status.PENDING_TEAM_LEAD, "3.00")
        ScopeProgressService.update_scope_progress(self.scope.id)
        self.scope.refresh_from_db()
        self.assertEqual(self.scope.cumulative_quantity, Decimal("3.00"))
        self.assertEqual(self.scope.progress_percentage, Decimal("2.50"))
        self.assertEqual(self.scope.remaining_quantity, Decimal("117.00"))

        # Day2 = 4 → (3+4)/120 = 5.83%
        self._make_dpr(1, DailyProgressReport.Status.PENDING_TEAM_LEAD, "4.00")
        ScopeProgressService.update_scope_progress(self.scope.id)
        self.scope.refresh_from_db()
        self.assertEqual(self.scope.cumulative_quantity, Decimal("7.00"))
        self.assertEqual(self.scope.progress_percentage, Decimal("5.83"))
        self.assertEqual(self.scope.remaining_quantity, Decimal("113.00"))

    def test_case2_day3_adds_more(self):
        self._make_dpr(0, DailyProgressReport.Status.APPROVED, "3.00")
        self._make_dpr(1, DailyProgressReport.Status.APPROVED, "4.00")
        self._make_dpr(2, DailyProgressReport.Status.APPROVED, "20.00")
        ScopeProgressService.update_scope_progress(self.scope.id)
        self.scope.refresh_from_db()
        # 27 / 120 = 22.50%
        self.assertEqual(self.scope.cumulative_quantity, Decimal("27.00"))
        self.assertEqual(self.scope.progress_percentage, Decimal("22.50"))
        self.assertEqual(self.scope.remaining_quantity, Decimal("93.00"))

    def test_case3_edit_day2_recalculates(self):
        self._make_dpr(0, DailyProgressReport.Status.APPROVED, "3.00")
        day2 = self._make_dpr(1, DailyProgressReport.Status.APPROVED, "4.00")
        ScopeProgressService.update_scope_progress(self.scope.id)

        day2.executed_quantity = Decimal("10.00")
        day2.save(update_fields=["executed_quantity"])
        ScopeProgressService.update_dpr_activity_progress(day2.id)

        self.scope.refresh_from_db()
        # 3 + 10 = 13 → 10.83%
        self.assertEqual(self.scope.cumulative_quantity, Decimal("13.00"))
        self.assertEqual(self.scope.progress_percentage, Decimal("10.83"))

    def test_case4_delete_day1_recalculates(self):
        day1 = self._make_dpr(0, DailyProgressReport.Status.APPROVED, "3.00")
        self._make_dpr(1, DailyProgressReport.Status.APPROVED, "4.00")
        ScopeProgressService.update_scope_progress(self.scope.id)

        day1.dpr.delete()  # cascades activity
        ScopeProgressService.update_scope_progress(self.scope.id)
        self.scope.refresh_from_db()
        self.assertEqual(self.scope.cumulative_quantity, Decimal("4.00"))
        self.assertEqual(self.scope.progress_percentage, Decimal("3.33"))

    def test_case5_rejected_excluded(self):
        self._make_dpr(0, DailyProgressReport.Status.APPROVED, "3.00")
        self._make_dpr(1, DailyProgressReport.Status.REJECTED, "4.00")
        ScopeProgressService.update_scope_progress(self.scope.id)
        self.scope.refresh_from_db()
        self.assertEqual(self.scope.cumulative_quantity, Decimal("3.00"))
        self.assertEqual(self.scope.progress_percentage, Decimal("2.50"))

    def test_draft_excluded_until_pending(self):
        self._make_dpr(0, DailyProgressReport.Status.PENDING_TEAM_LEAD, "3.00")
        day2 = self._make_dpr(1, DailyProgressReport.Status.DRAFT, "4.00")
        ScopeProgressService.update_scope_progress(self.scope.id)
        self.scope.refresh_from_db()
        self.assertEqual(self.scope.progress_percentage, Decimal("2.50"))

        day2.dpr.status = DailyProgressReport.Status.PENDING_TEAM_LEAD
        day2.dpr.save(update_fields=["status"])
        ScopeProgressService.recalculate_for_dpr(day2.dpr)
        self.scope.refresh_from_db()
        self.assertEqual(self.scope.progress_percentage, Decimal("5.83"))

    def test_case6_scopes_independent(self):
        scope_b = MonthlyScopeWork.objects.create(
            project=self.project,
            category=self.category,
            subcategory=self.subcategory,
            month=date(2026, 8, 1),
            description="Other scope planned 50",
            unit="Nos",
            planned_quantity=Decimal("50.00"),
            created_by=self.user,
        )
        self._make_dpr(0, DailyProgressReport.Status.APPROVED, "3.00")
        dpr_b = DailyProgressReport.objects.create(
            project_name=self.project.name,
            job_no="J-B",
            report_date=date(2026, 8, 2),
            issued_by="SE",
            designation="SE",
            status=DailyProgressReport.Status.APPROVED,
            created_by=self.user,
        )
        DPRActivity.objects.create(
            dpr=dpr_b, scope=scope_b, executed_quantity=Decimal("10.00")
        )

        ScopeProgressService.recalculate_scopes([self.scope.id, scope_b.id])
        self.scope.refresh_from_db()
        scope_b.refresh_from_db()
        self.assertEqual(self.scope.progress_percentage, Decimal("2.50"))
        self.assertEqual(scope_b.progress_percentage, Decimal("20.00"))

    def test_progress_capped_at_100(self):
        self._make_dpr(0, DailyProgressReport.Status.APPROVED, "100.00")
        self._make_dpr(1, DailyProgressReport.Status.APPROVED, "50.00")
        ScopeProgressService.update_scope_progress(self.scope.id)
        self.scope.refresh_from_db()
        self.assertEqual(self.scope.cumulative_quantity, Decimal("150.00"))
        self.assertEqual(self.scope.progress_percentage, Decimal("100.00"))
        self.assertEqual(self.scope.remaining_quantity, Decimal("0.00"))

    def test_activity_rows_get_running_cumulative(self):
        a1 = self._make_dpr(0, DailyProgressReport.Status.APPROVED, "3.00")
        a2 = self._make_dpr(1, DailyProgressReport.Status.APPROVED, "4.00")
        ScopeProgressService.update_scope_progress(self.scope.id)
        a1.refresh_from_db()
        a2.refresh_from_db()
        self.assertEqual(a1.cumulative_quantity, Decimal("3.00"))
        self.assertEqual(a1.progress_percentage, Decimal("2.50"))
        self.assertEqual(a2.cumulative_quantity, Decimal("7.00"))
        self.assertEqual(a2.progress_percentage, Decimal("5.83"))
