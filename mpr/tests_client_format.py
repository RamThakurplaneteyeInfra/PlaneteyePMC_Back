"""Client-format MPR PDF tests (SCL cover + engineering body from snapshot)."""

from __future__ import annotations

from io import BytesIO

from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from pypdf import PdfReader

from mpr.services.pdf_renderer import render_pdf
from mpr.services.report_config import (
    MPRStyleConfig,
    build_reference_number,
    get_mpr_report_config,
    get_mpr_style_config,
    month_year_label,
    resolve_logo_path,
)


def _minimal_snapshot(**overrides) -> dict:
    base = {
        "project": {
            "project_id": 42,
            "project_name": (
                "Design and Construction of Multi-Modal Transit Hub at "
                "Existing Thane Railway Station (East)"
            ),
            "project_code": "A3390",
            "client": "Thane Smart City Ltd.",
            "location": "Thane",
            "status": "active",
            "description": "Multi-modal transit hub construction scope.",
            "project_start": "2019-03-07",
            "contract_finish": "2022-03-06",
            "forecast_finish": "2026-05-31",
            "current_completion_date": "2026-08-15",
            "team_leader": "Team Leader",
            "consultant": "Shrikhande Consultants Limited",
        },
        "reporting_period": {
            "month": "2026-07",
            "start_date": "2026-07-01",
            "end_date": "2026-07-31",
        },
        "executive_summary": {
            "manual_input_required": True,
            "executive_summary": None,
            "auto": {
                "overall_status": "On Track",
                "progress_percentage": 35,
                "key_risks_count": 1,
            },
        },
        "key_indicators": {
            "progress_percentage": 35,
            "planned_progress_percentage": 40.0,
            "actual_progress_percentage": 35.0,
            "progress_variance": -5.0,
            "delay_days": 10,
            "contract_value": 1000000.0,
            "CPI": 0.95,
            "SPI": None,
            "EAC": 145.0,
            "BAC": 200.0,
            "eot_count": 2,
            "open_bottlenecks": 3,
            "cost_percentage": 70.0,
            "cost_status": "On Track",
            "project_status": "On Track",
            "progress_status": "Behind",
            "time_percentage": 80,
        },
        "physical_progress": {
            "monthly": {
                "reporting_month": "2026-07",
                "planned_percentage": 40.0,
                "actual_percentage": 35.0,
                "variance_percentage": -5.0,
                "available": True,
                "message": None,
            },
            "monthly_available": True,
            "reporting_month": "2026-07",
            "reporting_month_label": "July 2026",
            "cumulative": {
                "actual_percentage": 35.0,
                "scope_planned_quantity": 100.0,
                "scope_completed_quantity": 40.0,
                "scope_progress_percentage": 40.0,
                "available": True,
                "data_source": "scope",
            },
            "scope_progress": {
                "planned_quantity": 100.0,
                "cumulative_quantity": 40.0,
                "progress_percentage": 40.0,
                "available": True,
            },
            "activities": [
                {
                    "sr_no": 1,
                    "item": "Foundation",
                    "unit": "%",
                    "total": 100,
                    "completed": 100,
                    "balance": 0,
                    "percent_achieved": 100,
                    "remarks": "",
                },
                {
                    "sr_no": 2,
                    "item": "Substructure",
                    "unit": "%",
                    "total": 100,
                    "completed": 80,
                    "balance": 20,
                    "percent_achieved": 80,
                    "remarks": "",
                },
            ],
            "history": [
                {
                    "month": "2026-05",
                    "planned_percentage": 30,
                    "actual_percentage": 28,
                },
                {
                    "month": "2026-06",
                    "planned_percentage": 35,
                    "actual_percentage": 32,
                },
                {
                    "month": "2026-07",
                    "planned_percentage": 40,
                    "actual_percentage": 35,
                },
            ],
        },
        "time_progress": {
            "original_contract_finish": "2026-06-30",
            "current_completion_date": "2026-08-15",
            "elapsed_days": 100,
            "remaining_days": 20,
            "delay_days": -5,
            "time_percentage": 80,
            "status": "On Track",
            "project_status": "On Track",
        },
        "eot": {
            "eot_count": 2,
            "approved_count": 1,
            "latest_approved_eot": {
                "eot_number": 2,
                "extension_days": 45,
                "reason": "Design change",
                "approval_date": "2026-05-01",
                "revised_completion_date": "2026-08-15",
                "status": "approved",
            },
            "history": [
                {
                    "eot_number": 1,
                    "extension_days": 30,
                    "reason": "Pending rain",
                    "approval_date": None,
                    "revised_completion_date": "2026-12-31",
                    "status": "pending",
                },
                {
                    "eot_number": 2,
                    "extension_days": 45,
                    "reason": "Design change",
                    "approval_date": "2026-05-01",
                    "revised_completion_date": "2026-08-15",
                    "status": "approved",
                },
            ],
        },
        "financial_progress": {
            "contract": {
                "original_contract_value": 1000000.0,
                "revised_contract_value": 1040000.0,
            },
            "evm": {
                "BCWS": 100.0,
                "BCWP": 90.0,
                "ACWP": 95.0,
                "BAC": 200.0,
                "EAC": 145.0,
                "CPI": 0.947,
                "SPI": None,
                "CV": -5.0,
                "SV": -10.0,
            },
            "cashflow": None,
            "invoicing": {"records": []},
            "history": [
                {"month_year": "May-26", "BCWS": 80, "ACWP": 70, "BCWP": 75},
                {"month_year": "Jun-26", "BCWS": 90, "ACWP": 85, "BCWP": 88},
                {"month_year": "Jul-26", "BCWS": 100, "ACWP": 95, "BCWP": 90},
            ],
            "cashflow_history": [],
        },
        "bg": {
            "available": True,
            "records": [
                {
                    "bg_name": "Performance BG",
                    "bg_type": "SCL",
                    "due_date": "2026-12-31",
                    "updated_date": "2026-06-01",
                    "status": "UPDATED",
                }
            ],
        },
        "correspondence": {
            "summary": {"total_received": 1, "pending": 1},
            "important_records": [
                {
                    "sr_no": 1,
                    "received_date": "2026-07-05",
                    "description": "Pending client decision letter",
                    "correspondence_type": "CLIENT",
                    "delivered_status": "PENDING",
                }
            ],
        },
        "drawings": {
            "total_register": 5,
            "submitted": 3,
            "approved": 1,
            "pending": 2,
            "under_review": None,
            "rejected": None,
            "pending_items": [
                {
                    "sr_no": 1,
                    "drawing_name": "Foundation Plan",
                    "revision": 1,
                    "submitted_date": "2026-07-10",
                }
            ],
            "register_items": [
                {
                    "sr_no": 1,
                    "drawing_name": "Section-I GAD",
                    "revision": 1,
                    "submission_by_contractor": ["2019-09-19"],
                    "reply_by_scl": ["2019-11-22"],
                    "approved_date": "2019-12-13",
                    "remarks": "Approved",
                    "events": [],
                },
                {
                    "sr_no": 2,
                    "drawing_name": "Foundation Plan",
                    "revision": 1,
                    "submission_by_contractor": ["2026-07-10"],
                    "reply_by_scl": [],
                    "approved_date": None,
                    "remarks": "Under review",
                    "events": [],
                },
            ],
            "received_summary": {
                "total_drawings": 5,
                "received": 3,
                "reviewed": 3,
                "approved": 1,
                "pending": 4,
            },
            "balance_summary": {
                "pending_drawings": 4,
                "pending_with_contractor": 2,
                "pending_with_pmc": 2,
                "pending_with_client": None,
            },
        },
        "bottlenecks": {
            "new_count": 1,
            "resolved_count": None,
            "critical_count": 1,
            "overdue_count": 1,
            "open_count": 2,
            "records": [
                {
                    "description": "Client to approve VO",
                    "priority": "HIGH",
                    "status": "OPEN",
                    "target_date": "2026-07-20",
                    "ageing_days": 5,
                    "assigned_to": "PMC",
                    "is_overdue": True,
                    "type": "ISSUE",
                    "created_at": "2026-07-01",
                }
            ],
        },
        "quality": {
            "available": True,
            "tests_required": 10,
            "tests_conducted": 8,
            "tests_passed": 7,
            "tests_failed": 1,
            "pass_percentage": 70.0,
            "fail_percentage": 10.0,
            "quality_performance": 87.5,
        },
        "hse": {
            "available": True,
            "record": {
                "total_incidents": 3,
                "near_miss": 2,
                "ltifr": 0.5,
                "total_manhours": 10000,
                "man_days_worked": 1250,
                "average_daily_manpower": 50,
                "working_days": 25,
                "major": 0,
                "minor": 1,
                "fatalities": 0,
            },
        },
        "manpower": {
            "available": True,
            "planned_headcount": 100,
            "actual_headcount": 90,
            "planned_manhours": 20000,
            "actual_manhours": 18000,
        },
        "equipment": {
            "kpi": {
                "planned_equipment": 10,
                "actual_equipment": 8,
                "performance_percentage": 80.0,
            },
            "plant_machinery_reports": [
                {
                    "report_date": "2026-07-15",
                    "items": [
                        {"name": "Crane", "qty": 2, "status": "Working"},
                        {"name": "Lab Cube Mould", "qty": 12, "status": "Available"},
                    ],
                }
            ],
            "utilization_percentage": None,
        },
        "meetings": {
            "available": True,
            "records": [
                {
                    "meeting_type": "MOM",
                    "title": "Progress Review Meeting",
                    "description": "Monthly progress review",
                    "meeting_date": "2026-07-12",
                    "meeting_number": "12",
                }
            ],
        },
        "next_month_program": {
            "available": True,
            "month": "2026-08-01",
            "records": [
                {
                    "sr_no": 1,
                    "activity": "Pier Cap Casting",
                    "target": 4,
                    "unit": "Nos",
                    "planned_completion": "2026-08-31",
                    "remarks": "Priority",
                }
            ],
        },
        "site_photos": {
            "count": 1,
            "limit": 20,
            "photos": [
                {
                    "id": 1,
                    "title": "Tower A",
                    "image_url": "https://example.com/a.jpg",
                    "created_at": "2026-07-15T10:00:00",
                }
            ],
        },
        "data_availability": {},
    }
    base.update(overrides)
    return base


def _pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    parts = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(parts)


class ReportConfigTests(SimpleTestCase):
    def test_reference_uses_project_code(self):
        cfg = get_mpr_report_config()
        ref = build_reference_number(cfg, {"project_code": "A3390"})
        self.assertEqual(ref, "SCPL/SITE/A3390/")

    def test_month_year_label(self):
        name, year, label = month_year_label({"month": "2026-07"})
        self.assertEqual(name, "July")
        self.assertEqual(year, 2026)
        self.assertEqual(label, "July 2026")

    def test_style_config_and_logo(self):
        style = get_mpr_style_config()
        self.assertIsInstance(style, MPRStyleConfig)
        self.assertEqual(style.primary_brand_color, "#0072BC")
        logo = resolve_logo_path()
        self.assertIsNotNone(logo)
        self.assertTrue(logo.is_file())


class ClientFormatPDFTests(TestCase):
    def setUp(self):
        self.snapshot = _minimal_snapshot()
        self.pdf = render_pdf(self.snapshot, meta={"version": 2})
        self.text = _pdf_text(self.pdf)
        self.reader = PdfReader(BytesIO(self.pdf))

    def test_pdf_magic(self):
        self.assertTrue(self.pdf.startswith(b"%PDF"))

    def test_no_forwarding_letter(self):
        self.assertNotIn("Ref. No.", self.text)
        self.assertNotIn("The Chief Technical Officer", self.text)
        self.assertNotIn("Yours faithfully", self.text)
        self.assertNotIn("Thanking you, we remain", self.text)
        self.assertNotIn("Sir,", self.text)
        self.assertNotIn("Please find enclosed", self.text)
        self.assertNotIn("Team Leader", self.text.split("SALIENT")[0] if "SALIENT" in self.text else self.text[:500])
        # Signatory block from old letter must not appear as letter closing
        self.assertNotIn("(Sr. Bridge Engineer)", self.text)
        self.assertNotIn("SCPL/SITE/A3390/", self.text)

    def test_no_thane_smart_city_branding(self):
        # Client name may appear in project salient features as data,
        # but must NOT appear as report cover/header branding title alone.
        # Cover / early pages should not brand THANE SMART CITY LTD. as report owner.
        first_pages = "\n".join(
            (self.reader.pages[i].extract_text() or "")
            for i in range(min(2, len(self.reader.pages)))
        )
        self.assertNotIn("THANE SMART CITY LTD.", first_pages.upper())
        self.assertNotIn("WHERE PEACE MEETS PROSPERITY", self.text)

    def test_scl_branding_and_logo(self):
        self.assertIn("SHRIKHANDE CONSULTANTS LIMITED", self.text)
        self.assertIn("MONTHLY PROGRESS REPORT", self.text)
        self.assertTrue(resolve_logo_path().is_file())
        # Embedded JPEG from logo asset should appear in PDF stream
        self.assertIn(b"/Subtype /Image", self.pdf)

    def test_cover_and_index(self):
        self.assertIn("MONTHLY PROGRESS REPORT", self.text)
        self.assertIn("JULY 2026", self.text)
        self.assertIn("I N D E X", self.text)
        self.assertIn("Executive Summary", self.text)
        self.assertIn("Salient Features of the Project", self.text)
        self.assertIn("Status of Drawings", self.text)
        self.assertIn("Photographs", self.text)

    def test_section_order_headings(self):
        # Always-present core sections (empty backend sections are omitted)
        headings = [
            "1. EXECUTIVE SUMMARY",
            "2. SALIENT FEATURES OF THE PROJECT",
            "3. CONTRACTUAL OBLIGATIONS",
            "4. PROGRESS",
            "4.1 Physical Progress",
            "4.2 Bar Chart (Planned vs. Actual)",
            "4.3 Financial Progress",
            "4.4 Important Events",
            "5. QUALITY PERFORMANCE",
            "5.1 Material Testing",
            "6. BOTTLENECKS",
            "7. NEXT MONTH PROGRAM",
            "8. LIST OF PLANT AND MACHINERY",
            "9. LABORATORY EQUIPMENT AT SITE",
            "10. STATUS OF DRAWINGS",
            "10.1 Drawings Received",
            "10.2 Drawings Balance",
            "12. SAFETY ASPECT",
            "13. MEETINGS / SITE VISITS",
            "14. MANPOWER DEPLOYED (PMC)",
            "15. LABOUR MAN-DAY BAR CHART",
            "16. PHOTOGRAPHS",
        ]
        # Minimal snapshot has lab cube + meeting correspondence + safety + labour data
        positions = []
        for h in headings:
            idx = self.text.find(h)
            self.assertGreaterEqual(idx, 0, f"Missing heading: {h}")
            positions.append(idx)
        self.assertEqual(positions, sorted(positions))
        # Empty unavailable sections must not appear as "not available" stubs
        self.assertNotIn("11. MATERIAL RECEIVED AT SITE", self.text)
        self.assertNotIn("Material received register is not available", self.text)

    def test_physical_progress_table(self):
        self.assertIn("Foundation", self.text)
        self.assertIn("Substructure", self.text)
        self.assertIn("% Achieved", self.text)

    def test_charts_and_financial(self):
        self.assertTrue(
            "Planned vs Actual" in self.text
            or "Planned vs. Actual" in self.text
            or "Physical Progress — July 2026" in self.text
        )
        # Title / reporting period must stay July even when history is used
        self.assertTrue(
            "Physical Progress — July 2026" in self.text
            or "REPORTING PERIOD: JULY 2026" in self.text
            or "Report month 2026-07" in self.text
        )
        self.assertIn("BCWS", self.text)
        self.assertIn("Design change", self.text)

    def test_important_events_quality_bottlenecks(self):
        self.assertIn("Pending client decision", self.text)
        self.assertIn("Tests Required", self.text)
        self.assertIn("Client to approve VO", self.text)

    def test_next_month_plant_lab(self):
        self.assertIn("Pier Cap Casting", self.text)
        self.assertIn("Crane", self.text)
        self.assertIn("Lab Cube Mould", self.text)

    def test_drawings_detailed_status(self):
        self.assertIn("Section-I GAD", self.text)
        self.assertIn("Submission by", self.text)
        self.assertIn("Contractor", self.text)
        self.assertIn("Reply by SCL", self.text)
        self.assertIn("Drawings Received", self.text)
        self.assertIn("Drawings Balance", self.text)
        self.assertIn("Foundation Plan", self.text)

    def test_safety_meetings_manpower_labour(self):
        self.assertIn("Near Miss", self.text)
        self.assertIn("Progress Review Meeting", self.text)
        self.assertIn("Planned Headcount", self.text)
        self.assertIn("LABOUR MAN-DAY", self.text)

    def test_photos_section_and_caption(self):
        self.assertIn("PHOTOGRAPHS", self.text)
        self.assertIn("Tower A", self.text)

    def test_page_numbers(self):
        # Header/footer drawn on canvas — appear in extracted text on later pages
        joined = self.text
        self.assertTrue(
            "Page " in joined or len(self.reader.pages) >= 3,
            "Expected multi-page PDF with page markers",
        )
        self.assertGreaterEqual(len(self.reader.pages), 4)

    def test_no_backend_jargon(self):
        self.assertNotIn("snapshot_note", self.text)
        self.assertNotIn("ScopeProgressService", self.text)
        self.assertNotIn("Narrative text fields are not stored yet", self.text)
        self.assertNotIn("closed_at", self.text)
        self.assertNotIn("ConstructionProgress row", self.text)

    def test_version_shown(self):
        self.assertIn("v2", self.text)

    def test_no_db_queries(self):
        with CaptureQueriesContext(connection) as ctx:
            render_pdf(self.snapshot, meta={"version": 1})
        self.assertEqual(len(ctx), 0)

    def test_march_month_dynamic(self):
        snap = _minimal_snapshot(
            reporting_period={
                "month": "2026-03",
                "start_date": "2026-03-01",
                "end_date": "2026-03-31",
            }
        )
        text = _pdf_text(render_pdf(snap, meta={"version": 1}))
        self.assertIn("March 2026", text)
        self.assertNotIn("FOR JULY 2026", text.upper())
