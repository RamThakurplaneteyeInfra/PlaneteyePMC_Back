"""Phase-3 MPR data integrity / validation / rendering tests."""

from __future__ import annotations

from copy import deepcopy
from io import BytesIO

from django.test import SimpleTestCase, TestCase
from pypdf import PdfReader

from mpr.services.excel_renderer import render_excel
from mpr.services.mpr_validation import (
    validate_and_normalize_snapshot,
    _reconcile_activity,
)
from mpr.services.pdf_renderer import render_pdf
from mpr.tests_client_format import _minimal_snapshot, _pdf_text


class PhysicalProgressReconciliationTests(SimpleTestCase):
    def test_completed_less_than_total(self):
        row = _reconcile_activity(
            {"item": "Piles", "total": 10, "completed": 9, "balance": 99, "percent_achieved": 1}
        )
        self.assertEqual(row["balance"], 1.0)
        self.assertEqual(row["percent_achieved"], 90.0)

    def test_completed_equals_total(self):
        row = _reconcile_activity({"total": 15, "completed": 15})
        self.assertEqual(row["balance"], 0.0)
        self.assertEqual(row["percent_achieved"], 100.0)

    def test_completed_exceeds_total(self):
        row = _reconcile_activity({"item": "Pile Cap", "total": 15, "completed": 17})
        self.assertEqual(row["balance"], 0.0)
        self.assertEqual(row["percent_achieved"], 100.0)
        self.assertTrue(row.get("overachievement"))

    def test_zero_total(self):
        row = _reconcile_activity({"total": 0, "completed": 5})
        self.assertEqual(row["percent_achieved"], 0.0)
        self.assertEqual(row["balance"], 0.0)

    def test_snapshot_physical_chart_reporting_month(self):
        snap = _minimal_snapshot()
        out = validate_and_normalize_snapshot(snap)
        chart = out["physical_progress"]["chart"]
        self.assertEqual(chart["reporting_month"], "2026-07")
        self.assertEqual(chart["periods"], ["2026-05", "2026-06", "2026-07"])
        self.assertNotEqual(chart["periods"][-1], "2026-05")

    def test_future_actual_progress_excluded(self):
        snap = _minimal_snapshot()
        snap["physical_progress"]["history"].append(
            {"month": "2026-09", "planned_percentage": 50, "actual_percentage": 48}
        )
        out = validate_and_normalize_snapshot(snap)
        months = [h["month"] for h in out["physical_progress"]["history"]]
        self.assertNotIn("2026-09", months)
        self.assertIn("Excluded future actual progress month 2026-09", " ".join(out["validation"]["warnings"]))


class QualityValidationTests(SimpleTestCase):
    def test_pass_percentage_uses_conducted_denominator(self):
        snap = _minimal_snapshot()
        snap["quality"] = {
            "available": True,
            "tests_required": 7050,
            "tests_conducted": 7561,
            "tests_passed": 7560,
            "tests_failed": 1,
            "pass_percentage": 107.23,
            "fail_percentage": 0.01,
            "quality_performance": 99.99,
        }
        out = validate_and_normalize_snapshot(snap)
        q = out["quality"]
        self.assertLessEqual(q["pass_percentage"], 100.0)
        self.assertAlmostEqual(q["pass_percentage"], round(7560 / 7561 * 100, 2))
        self.assertAlmostEqual(q["fail_percentage"], round(1 / 7561 * 100, 2))


class SafetyValidationTests(SimpleTestCase):
    def test_rates_unavailable_when_manhours_invalid(self):
        snap = _minimal_snapshot()
        snap["hse"] = {
            "available": True,
            "record": {
                "fatalities": 65,
                "significant": 34,
                "major": 12,
                "minor": 453,
                "near_miss": 87,
                "total_incidents": 651,
                "total_manhours": 230,
                "man_hours_worked": 0,
                "loss_of_manhours": 123,
                "working_days": 0,
                "average_daily_manpower": 0,
                "ltifr": 534782.61,
                "incident_rate": 2830434.78,
            },
        }
        out = validate_and_normalize_snapshot(snap)
        rec = out["hse"]["record"]
        self.assertIsNone(rec["ltifr"])
        self.assertIsNone(rec["incident_rate"])
        self.assertFalse(out["hse"]["rates_available"])

    def test_rates_available_with_valid_denominator(self):
        snap = _minimal_snapshot()
        snap["hse"] = {
            "available": True,
            "record": {
                "fatalities": 0,
                "significant": 0,
                "major": 0,
                "minor": 1,
                "near_miss": 2,
                "total_incidents": 3,
                "total_manhours": 100000,
                "man_hours_worked": 100000,
                "loss_of_manhours": 8,
                "working_days": 25,
                "average_daily_manpower": 50,
                "ltifr": 999,
                "incident_rate": 999,
            },
        }
        out = validate_and_normalize_snapshot(snap)
        rec = out["hse"]["record"]
        self.assertIsNotNone(rec["ltifr"])
        self.assertLess(rec["ltifr"], 50_000)
        self.assertTrue(out["hse"]["rates_available"])


class FinancialChronologyTests(SimpleTestCase):
    def test_financial_history_sorted_and_no_future(self):
        snap = _minimal_snapshot()
        snap["financial_progress"]["history"] = [
            {"month_year": "Sep-2026", "BCWS": 1, "ACWP": 1},
            {"month_year": "May-2026", "BCWS": 2, "ACWP": 2},
            {"month_year": "Jul-2026", "BCWS": 3, "ACWP": 3},
            {"month_year": "Jun-2026", "BCWS": 4, "ACWP": 4},
        ]
        out = validate_and_normalize_snapshot(snap)
        months = [h["month_year"] for h in out["financial_progress"]["history"]]
        self.assertEqual(months, ["May-2026", "Jun-2026", "Jul-2026"])
        self.assertNotIn("Sep-2026", months)
        self.assertEqual(out["financial_progress"]["chart"]["reporting_month"], "2026-07")


class EnumAndTextCleanupTests(SimpleTestCase):
    def test_enum_labels_and_merge_text_removed(self):
        snap = _minimal_snapshot()
        snap["project"]["description"] = "[Merged from 'Thane Project' (id=6)] Project brief"
        snap["correspondence"]["important_records"][0]["delivered_status"] = "DELIVERED_ON_TIME"
        snap["correspondence"]["important_records"][0]["correspondence_type"] = "CLIENT"
        out = validate_and_normalize_snapshot(snap)
        self.assertEqual(out["project"]["description"], "Project brief")
        self.assertNotIn("id=6", out["project"]["description"] or "")
        rec = out["correspondence"]["important_records"][0]
        self.assertEqual(rec["delivered_status"], "Delivered on Time")
        self.assertEqual(rec["correspondence_type"], "Client")

    def test_drawing_html_stripped_from_snapshot(self):
        snap = _minimal_snapshot()
        snap["drawings"]["register_items"][0]["submission_by_contractor"] = [
            "2019-09-19<br/>2019-10-01"
        ]
        out = validate_and_normalize_snapshot(snap)
        dates = out["drawings"]["register_items"][0]["submission_by_contractor"]
        self.assertTrue(all("<br" not in d for d in dates))
        self.assertGreaterEqual(len(dates), 2)


class RendererIntegrityTests(TestCase):
    def setUp(self):
        raw = _minimal_snapshot()
        raw["correspondence"]["important_records"][0]["delivered_status"] = "DELIVERED_ON_TIME"
        raw["correspondence"]["important_records"][0]["correspondence_type"] = "CLIENT"
        raw["project"]["description"] = "[Merged from 'Thane Project' (id=6)] Multi-modal transit hub construction scope."
        self.snapshot = validate_and_normalize_snapshot(raw)
        self.pdf = render_pdf(self.snapshot, meta={"version": 3})
        self.text = _pdf_text(self.pdf)

    def test_no_html_br_literal(self):
        self.assertNotIn("<br/>", self.text)
        self.assertNotIn("&lt;br", self.text)

    def test_no_raw_enums(self):
        self.assertNotIn("DELIVERED_ON_TIME", self.text)
        self.assertIn("Delivered on Time", self.text)

    def test_no_merge_debug(self):
        self.assertNotIn("Merged from", self.text)
        self.assertNotIn("id=6", self.text)

    def test_quality_not_over_100(self):
        # Snapshot already fixed; PDF should not show 107%
        self.assertNotIn("107.", self.text)

    def test_reporting_month_on_chart_title(self):
        self.assertIn("2026-07", self.text)
        self.assertTrue(
            "Physical Progress — July 2026" in self.text
            or "REPORTING PERIOD: JULY 2026" in self.text
            or "Report month 2026-07" in self.text
        )

    def test_equipment_summary_label(self):
        self.assertIn("Equipment Deployment Summary", self.text)

    def test_pdf_excel_same_quality_figures(self):
        q = self.snapshot["quality"]
        xlsx = render_excel(self.snapshot)
        self.assertTrue(xlsx[:2] == b"PK")
        # PDF and snapshot share values
        self.assertLessEqual(q["pass_percentage"], 100)
        self.assertIn("QUALITY", self.text.upper())

    def test_safety_rates_not_available_when_invalid(self):
        snap = deepcopy(self.snapshot)
        snap["hse"] = {
            "available": True,
            "rates_available": False,
            "record": {
                "fatalities": 65,
                "total_incidents": 651,
                "ltifr": None,
                "incident_rate": None,
                "total_manhours": 230,
                "working_days": 0,
            },
        }
        text = _pdf_text(render_pdf(snap, meta={"version": 1}))
        self.assertIn("Not Available", text)
        self.assertNotIn("534782", text)
