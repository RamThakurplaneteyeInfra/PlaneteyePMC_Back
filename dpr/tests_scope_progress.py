"""
Regression tests: Assigned Scope cumulative = SUM of non-rejected DPR executed qty.

Case: Planned=120, Day1=4, Day2=3 → cumulative=7, progress=5.83%
Draft counts on Create; rejected does not.
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
        self.user = User.objects.create_user(username="prog_se2", password="testpass123")
        self.project = Project.objects.create(name="Progress Cumul Project 2", status="active")
        self.category = ScopeCategory.objects.create(name="Civil-Prog2", display_order=1)
        self.subcategory = ScopeSubCategory.objects.create(
            category=self.category, name="Excavation-Prog2", display_order=1
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
            job_no="J-PROG2",
            report_date=date(2026, 8, 1) + timedelta(days=day_offset),
            issued_by="SE",
            designation="Site Engineer",
            status=status,
            submitted_by=self.user,
            created_by=self.user,
        )
        activity = DPRActivity.objects.create(
            dpr=dpr,
            scope=self.scope,
            executed_quantity=Decimal(executed),
        )
        ScopeProgressService.update_dpr_activity_progress(activity.id)
        activity.refresh_from_db()
        self.scope.refresh_from_db()
        return activity

    def test_day1_4_day2_3_cumulative_7(self):
        """Primary bug case: 4 + 3 = 7 → 5.83% (including draft create)."""
        day1 = self._make_dpr(0, DailyProgressReport.Status.DRAFT, "4.00")
        self.assertEqual(self.scope.cumulative_quantity, Decimal("4.00"))
        self.assertEqual(self.scope.progress_percentage, Decimal("3.33"))
        self.assertEqual(day1.cumulative_quantity, Decimal("4.00"))

        day2 = self._make_dpr(1, DailyProgressReport.Status.DRAFT, "3.00")
        self.assertEqual(self.scope.cumulative_quantity, Decimal("7.00"))
        self.assertEqual(self.scope.progress_percentage, Decimal("5.83"))
        self.assertEqual(self.scope.remaining_quantity, Decimal("113.00"))
        self.assertEqual(day2.cumulative_quantity, Decimal("7.00"))
        self.assertEqual(day2.progress_percentage, Decimal("5.83"))

    def test_pending_and_approved_also_sum(self):
        self._make_dpr(0, DailyProgressReport.Status.PENDING_TEAM_LEAD, "4.00")
        self._make_dpr(1, DailyProgressReport.Status.APPROVED, "3.00")
        self.assertEqual(self.scope.cumulative_quantity, Decimal("7.00"))
        self.assertEqual(self.scope.progress_percentage, Decimal("5.83"))

    def test_edit_day2_recalculates(self):
        self._make_dpr(0, DailyProgressReport.Status.DRAFT, "4.00")
        day2 = self._make_dpr(1, DailyProgressReport.Status.DRAFT, "3.00")

        day2.executed_quantity = Decimal("10.00")
        day2.save(update_fields=["executed_quantity"])
        ScopeProgressService.update_dpr_activity_progress(day2.id)
        self.scope.refresh_from_db()

        # 4 + 10 = 14 → 11.67%
        self.assertEqual(self.scope.cumulative_quantity, Decimal("14.00"))
        self.assertEqual(self.scope.progress_percentage, Decimal("11.67"))

    def test_delete_day1_recalculates(self):
        day1 = self._make_dpr(0, DailyProgressReport.Status.DRAFT, "4.00")
        self._make_dpr(1, DailyProgressReport.Status.DRAFT, "3.00")
        self.assertEqual(self.scope.cumulative_quantity, Decimal("7.00"))

        day1.dpr.delete()
        ScopeProgressService.update_scope_progress(self.scope.id)
        self.scope.refresh_from_db()
        self.assertEqual(self.scope.cumulative_quantity, Decimal("3.00"))
        self.assertEqual(self.scope.progress_percentage, Decimal("2.50"))

    def test_rejected_excluded(self):
        self._make_dpr(0, DailyProgressReport.Status.DRAFT, "4.00")
        rejected = self._make_dpr(1, DailyProgressReport.Status.DRAFT, "3.00")
        self.assertEqual(self.scope.cumulative_quantity, Decimal("7.00"))

        rejected.dpr.status = DailyProgressReport.Status.REJECTED
        rejected.dpr.save(update_fields=["status"])
        ScopeProgressService.recalculate_for_dpr(rejected.dpr)
        self.scope.refresh_from_db()

        # Only day1 remains
        self.assertEqual(self.scope.cumulative_quantity, Decimal("4.00"))
        self.assertEqual(self.scope.progress_percentage, Decimal("3.33"))

    def test_scopes_independent(self):
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
        self._make_dpr(0, DailyProgressReport.Status.DRAFT, "4.00")
        dpr_b = DailyProgressReport.objects.create(
            project_name=self.project.name,
            job_no="J-B2",
            report_date=date(2026, 8, 2),
            issued_by="SE",
            designation="SE",
            status=DailyProgressReport.Status.DRAFT,
            created_by=self.user,
        )
        act_b = DPRActivity.objects.create(
            dpr=dpr_b, scope=scope_b, executed_quantity=Decimal("10.00")
        )
        ScopeProgressService.recalculate_scopes([self.scope.id, scope_b.id])
        self.scope.refresh_from_db()
        scope_b.refresh_from_db()
        self.assertEqual(self.scope.cumulative_quantity, Decimal("4.00"))
        self.assertEqual(scope_b.cumulative_quantity, Decimal("10.00"))
        self.assertEqual(scope_b.progress_percentage, Decimal("20.00"))
        self.assertIsNotNone(act_b.id)

    def test_never_use_latest_only(self):
        """Guard: cumulative must be SUM, not overwrite with latest day qty."""
        self._make_dpr(0, DailyProgressReport.Status.DRAFT, "4.00")
        self._make_dpr(1, DailyProgressReport.Status.DRAFT, "3.00")
        # If overwritten with latest only, would be 3.00 / 2.50%
        self.assertNotEqual(self.scope.cumulative_quantity, Decimal("3.00"))
        self.assertEqual(self.scope.cumulative_quantity, Decimal("7.00"))
