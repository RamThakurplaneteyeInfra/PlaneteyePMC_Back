"""Plant & machinery inventory — full catalogue including zero qty."""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from pypdf import PdfReader
from io import BytesIO

from plant_machinery.models import MachineryItem, MachineryMaster, PlantMachineryReport
from project_equipment.models.project_equipment import ProjectEquipment
from mpr.services.mpr_service import MPRService
from mpr.services.period import parse_mpr_month
from mpr.services.pdf_renderer import render_pdf
from projects.models import Project

User = get_user_model()


class PlantMachineryInventoryTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="mpr_plant_admin",
            email="mpr_plant@example.com",
            password="pass12345",
            is_staff=True,
            is_superuser=True,
        )
        self.project = Project.objects.create(
            name="B9400 Plant Machinery Project",
            client_name="Test Client",
            location="Pune",
            status="active",
            project_start=date(2025, 1, 1),
            contract_finish=date(2026, 12, 31),
            team_lead=self.user,
        )
        self.period = parse_mpr_month("2026-07")
        self.m1 = MachineryMaster.objects.create(
            name="Alpha Excavator", unit="Nos", category="Earthmoving"
        )
        self.m2 = MachineryMaster.objects.create(
            name="Beta Crane", unit="Nos", category="Lifting"
        )
        self.m3 = MachineryMaster.objects.create(
            name="Gamma Pump", unit="Nos", category="Pumping"
        )

    def _build(self):
        return MPRService(self.project, self.period).build()

    def test_all_masters_shown_with_zero_when_no_report(self):
        snap = self._build()
        inv = snap["equipment"]["inventory"]
        names = {i["name"] for i in inv}
        self.assertIn(self.m1.name, names)
        self.assertIn(self.m2.name, names)
        self.assertIn(self.m3.name, names)
        self.assertEqual(snap["equipment"]["count"], len(inv))
        self.assertTrue(all(i["qty"] == 0 for i in inv if i["name"] in names))
        self.assertEqual(snap["equipment"]["total_quantity"], 0)

    def test_partial_report_fills_counts_others_zero(self):
        report = PlantMachineryReport.objects.create(
            project_name=self.project.name,
            report_date=date(2026, 7, 15),
        )
        MachineryItem.objects.create(
            report=report,
            machinery_master=self.m2,
            sr_no=1,
            qty=3,
            status="Working",
        )
        snap = self._build()
        by_name = {i["name"]: i for i in snap["equipment"]["inventory"]}
        self.assertEqual(by_name[self.m2.name]["qty"], 3)
        self.assertEqual(by_name[self.m1.name]["qty"], 0)
        self.assertEqual(by_name[self.m3.name]["qty"], 0)
        self.assertEqual(snap["equipment"]["count"], 3)
        self.assertEqual(snap["equipment"]["total_quantity"], 3)
        self.assertEqual(snap["equipment"]["source_report_date"], "2026-07-15")

        text = "\n".join(
            page.extract_text() or ""
            for page in PdfReader(BytesIO(render_pdf(snap, meta={"version": 1}))).pages
        )
        self.assertIn("Total plant & machinery types: 3", text)
        self.assertIn(self.m1.name, text)
        self.assertIn(self.m2.name, text)
        self.assertIn(self.m3.name, text)

    def test_july_uses_latest_report_on_or_before_month_end(self):
        report = PlantMachineryReport.objects.create(
            project_name=self.project.name,
            report_date=date(2026, 6, 10),
        )
        MachineryItem.objects.create(
            report=report,
            machinery_master=self.m1,
            sr_no=1,
            qty=5,
            status="Working",
        )
        snap = self._build()
        by_name = {i["name"]: i for i in snap["equipment"]["inventory"]}
        self.assertEqual(by_name[self.m1.name]["qty"], 5)
        self.assertEqual(snap["equipment"]["source_report_date"], "2026-06-10")
        self.assertEqual(snap["equipment"]["count"], 3)
