"""Executive Summary — physical/financial billed-till-date aggregation tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase

from construction_progress.models.construction_progress import ConstructionProgress
from contract_values.models import ContractValue
from cost_performance.models import ProjectCostPerformance
from invoicing.models import InvoicingInformation
from monthly_scope.models import MonthlyScopeWork, ScopeCategory, ScopeSubCategory
from mpr.services.mpr_service import MPRService
from mpr.services.period import parse_mpr_month
from projects.models import Project

User = get_user_model()


class ExecutiveBilledTillDateTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="mpr_billed_admin",
            email="mpr_billed@example.com",
            password="pass12345",
            is_staff=True,
            is_superuser=True,
        )
        self.project = Project.objects.create(
            name="B9100 Billed Till Date Project",
            client_name="Test Client",
            location="Pune",
            status="active",
            project_start=date(2025, 1, 1),
            contract_finish=date(2026, 12, 31),
            team_lead=self.user,
        )
        self.month = "2026-07"
        self.period = parse_mpr_month(self.month)
        self.cat = ScopeCategory.objects.create(name="Civil-Billed")
        self.sub = ScopeSubCategory.objects.create(
            category=self.cat, name="Excavation-Billed"
        )

    def _build(self):
        return MPRService(self.project, self.period).build()

    def _scope(self, planned, cumulative, month=None):
        MonthlyScopeWork.objects.create(
            project=self.project,
            category=self.cat,
            subcategory=self.sub,
            month=month or date(2026, 5, 1),
            planned_quantity=Decimal(str(planned)),
            cumulative_quantity=Decimal(str(cumulative)),
            unit="cum",
        )

    def _contract(self, original="1000000", excess="0", saving="0"):
        return ContractValue.objects.create(
            project_name=self.project.name,
            contract_type=ContractValue.ContractType.SCL,
            original_contract_value=Decimal(original),
            excess_value=Decimal(excess),
            saving=Decimal(saving),
        )

    def _scl_invoice(self, billed="250000", certified="200000"):
        return InvoicingInformation.objects.create(
            project_name=self.project.name,
            invoice_type=InvoicingInformation.InvoiceType.SCL,
            gross_billed=Decimal(billed),
            gross_certified_billed=Decimal(certified),
        )

    # ------------------------------------------------------------------
    # Physical
    # ------------------------------------------------------------------

    def test_physical_july_construction_progress_exists(self):
        ConstructionProgress.objects.create(
            projectName=self.project.name,
            progressMonth=self.month,
            plannedProgress=Decimal("50.00"),
            actualProgress=Decimal("40.00"),
        )
        self._scope(100, 40)
        snap = self._build()
        billed = snap["executive_summary"]["physical_progress_billed_till_date"]
        self.assertEqual(billed["target_percentage"], 50.0)
        self.assertEqual(billed["actual_percentage"], 40.0)
        self.assertTrue(billed["target_available"])
        self.assertTrue(billed["actual_available"])

    def test_physical_july_cp_missing_but_scope_exists(self):
        """May CP must not fill July target; scope still drives actual."""
        ConstructionProgress.objects.create(
            projectName=self.project.name,
            progressMonth="2026-05",
            plannedProgress=Decimal("45.00"),
            actualProgress=Decimal("40.00"),
        )
        self._scope(120, 25.08)
        snap = self._build()
        billed = snap["executive_summary"]["physical_progress_billed_till_date"]
        self.assertIsNone(billed["target_percentage"])
        self.assertFalse(billed["target_available"])
        self.assertAlmostEqual(billed["actual_percentage"], 20.9, places=1)
        self.assertEqual(billed["planned_quantity"], 120.0)
        self.assertEqual(billed["cumulative_quantity"], 25.08)
        self.assertTrue(billed["actual_available"])
        # Must not invent zero target
        self.assertIsNotNone(billed["actual_percentage"])
        self.assertNotEqual(billed["actual_percentage"], 0)

    def test_physical_no_progress_data(self):
        snap = self._build()
        billed = snap["executive_summary"]["physical_progress_billed_till_date"]
        self.assertIsNone(billed["target_percentage"])
        self.assertIsNone(billed["actual_percentage"])
        self.assertFalse(billed["available"])

    def test_physical_cumulative_progress_calculation(self):
        self._scope(200, 50)
        self._scope(100, 25, month=date(2026, 6, 1))
        snap = self._build()
        billed = snap["executive_summary"]["physical_progress_billed_till_date"]
        # (50+25)/(200+100)*100 = 25
        self.assertEqual(billed["actual_percentage"], 25.0)
        self.assertEqual(billed["planned_quantity"], 300.0)
        self.assertEqual(billed["cumulative_quantity"], 75.0)

    # ------------------------------------------------------------------
    # Financial
    # ------------------------------------------------------------------

    def test_financial_invoices_exist(self):
        self._contract(original="54925279", excess="0", saving="0")
        self._scl_invoice(billed="55376980", certified="52765738")
        snap = self._build()
        billed = snap["executive_summary"]["financial_progress_billed_till_date"]
        self.assertEqual(billed["target_amount"], 54925279.0)
        self.assertEqual(billed["actual_amount"], 55376980.0)
        self.assertEqual(billed["certified_amount"], 52765738.0)
        self.assertTrue(billed["actual_available"])
        self.assertEqual(billed["data_source"], "invoicing_scl_gross_billed")

    def test_financial_does_not_use_contractor_against_scl_target(self):
        self._contract(original="1000000")
        InvoicingInformation.objects.create(
            project_name=self.project.name,
            invoice_type=InvoicingInformation.InvoiceType.CONTRACTOR,
            contractor_name="Contractor A",
            gross_billed=Decimal("999999999"),
            gross_certified_billed=Decimal("888888888"),
        )
        snap = self._build()
        billed = snap["executive_summary"]["financial_progress_billed_till_date"]
        self.assertEqual(billed["target_amount"], 1000000.0)
        self.assertIsNone(billed["actual_amount"])
        self.assertFalse(billed["actual_available"])

    def test_financial_multiple_invoice_types_uses_scl_gross_billed(self):
        self._contract(original="1000000")
        self._scl_invoice(billed="400000", certified="350000")
        InvoicingInformation.objects.create(
            project_name=self.project.name,
            invoice_type=InvoicingInformation.InvoiceType.CONTRACTOR,
            contractor_name="Contractor A",
            gross_billed=Decimal("9000000"),
            gross_certified_billed=Decimal("8000000"),
        )
        snap = self._build()
        billed = snap["executive_summary"]["financial_progress_billed_till_date"]
        self.assertEqual(billed["actual_amount"], 400000.0)

    def test_financial_no_invoice_keeps_actual_null_not_zero(self):
        self._contract(original="1000000")
        # Cost row must not become billed actual
        ProjectCostPerformance.objects.create(
            project=self.project,
            project_name=self.project.name,
            month_year="Jul-2026",
            bcws=Decimal("110000"),
            bcwp=Decimal("100000"),
            acwp=Decimal("123456"),
            fcst=Decimal("50000"),
            bac=Decimal("1000000"),
        )
        snap = self._build()
        billed = snap["executive_summary"]["financial_progress_billed_till_date"]
        self.assertEqual(billed["target_amount"], 1000000.0)
        self.assertIsNone(billed["actual_amount"])
        self.assertNotEqual(billed["actual_amount"], 0)

    def test_financial_deleted_invoice_unavailable(self):
        self._contract(original="1000000")
        inv = self._scl_invoice(billed="250000")
        inv.delete()
        snap = self._build()
        billed = snap["executive_summary"]["financial_progress_billed_till_date"]
        self.assertIsNone(billed["actual_amount"])

    def test_financial_revised_contract_is_target(self):
        self._contract(original="39306007", excess="15619272", saving="0")
        snap = self._build()
        billed = snap["executive_summary"]["financial_progress_billed_till_date"]
        self.assertEqual(billed["target_amount"], 54925279.0)

    def test_financial_invoicing_has_no_rejected_status_field(self):
        """Model is current-state KPI rows; no rejected/cancelled status to exclude."""
        field_names = {f.name for f in InvoicingInformation._meta.get_fields()}
        self.assertNotIn("status", field_names)
        self.assertNotIn("invoice_date", field_names)
        self.assertNotIn("bill_date", field_names)

    # ------------------------------------------------------------------
    # Executive summary combinations
    # ------------------------------------------------------------------

    def test_exec_both_available(self):
        ConstructionProgress.objects.create(
            projectName=self.project.name,
            progressMonth=self.month,
            plannedProgress=Decimal("50.00"),
            actualProgress=Decimal("40.00"),
        )
        self._scope(100, 40)
        self._contract(original="1000000")
        self._scl_invoice(billed="250000")
        snap = self._build()
        phys = snap["executive_summary"]["physical_progress_billed_till_date"]
        fin = snap["executive_summary"]["financial_progress_billed_till_date"]
        self.assertTrue(phys["target_available"] and phys["actual_available"])
        self.assertTrue(fin["target_available"] and fin["actual_available"])

    def test_exec_target_available_actual_unavailable(self):
        self._contract(original="1000000")
        snap = self._build()
        fin = snap["executive_summary"]["financial_progress_billed_till_date"]
        self.assertTrue(fin["target_available"])
        self.assertFalse(fin["actual_available"])
        self.assertIsNone(fin["actual_amount"])

    def test_exec_neither_available(self):
        snap = self._build()
        phys = snap["executive_summary"]["physical_progress_billed_till_date"]
        fin = snap["executive_summary"]["financial_progress_billed_till_date"]
        self.assertFalse(phys["available"])
        self.assertFalse(fin["available"])
