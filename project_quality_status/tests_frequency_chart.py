"""Tests for frequency chart client report."""

from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from core.test_auth import authenticate_client

from .controllers.frequency_chart_report import (
    VIEW_CUMULATIVE,
    VIEW_MONTHLY,
    build_client_row,
    filter_frequency_chart_queryset,
    required_tests_for_quantity,
)
from .models.frequency_chart import FrequencyChartEntry, TestFrequencyMaster
from .models.project_quality_status import ProjectQualityStatus


class FrequencyChartCalculationTest(TestCase):
    def test_required_tests_from_frequency(self):
        self.assertEqual(required_tests_for_quantity(500, 1, 30), 17)
        self.assertEqual(required_tests_for_quantity(150, 1, 30), 5)
        self.assertEqual(required_tests_for_quantity(0, 1, 30), 0)
        self.assertIsNone(required_tests_for_quantity(100, None, None))

    def test_build_client_row(self):
        master = TestFrequencyMaster.objects.create(
            item_description="Concrete",
            type_of_test="Compressive Strength",
            unit="Cum",
            frequency_value=Decimal("1"),
            frequency_quantity=Decimal("30"),
        )
        entry = FrequencyChartEntry.objects.create(
            projectName="Thane Project",
            month=6,
            year=2026,
            sr_no=1,
            item_description="Concrete",
            type_of_test="Compressive Strength",
            unit="Cum",
            frequency_master=master,
            qty_previous_bill=Decimal("500"),
            qty_this_bill=Decimal("150"),
            field_lab_previous_bill=15,
            field_lab_this_bill=4,
            third_party_previous_bill=2,
            third_party_this_bill=1,
            remarks="Complied",
        )
        row = build_client_row(entry)
        self.assertEqual(row["required_tests_previous_bill"], 17)
        self.assertEqual(row["required_tests_this_bill"], 5)
        self.assertEqual(row["required_tests_upto_date"], 22)
        self.assertEqual(row["total_tests_conducted"], 22)
        self.assertEqual(row["total_qty"], 650.0)


class FrequencyChartAPITest(APITestCase):
    CHART_URL = "/api/frequency-chart/"
    REGISTER_URL = "/api/frequency-chart/register/"

    def setUp(self):
        authenticate_client(self.client)
        TestFrequencyMaster.objects.create(
            item_description="Concrete",
            type_of_test="Compressive Strength",
            unit="Cum",
            frequency_value=Decimal("1"),
            frequency_quantity=Decimal("30"),
        )
        FrequencyChartEntry.objects.filter(projectName="Thane Project").delete()
        FrequencyChartEntry.objects.create(
            projectName="Thane Project",
            month=6,
            year=2026,
            sr_no=1,
            item_description="Concrete",
            type_of_test="Compressive Strength",
            unit="Cum",
            qty_previous_bill=Decimal("500"),
            qty_this_bill=Decimal("150"),
            field_lab_previous_bill=15,
            field_lab_this_bill=4,
            third_party_previous_bill=2,
            third_party_this_bill=1,
            remarks="Complied",
        )
        ProjectQualityStatus.objects.create(
            projectName="Thane Project",
            month=6,
            year=2026,
            tests_required=22,
            tests_conducted=22,
            tests_passed=22,
            tests_failed=0,
        )

    def test_client_report_monthly(self):
        response = self.client.get(
            self.CHART_URL,
            {
                "format": "client",
                "project_name": "Thane Project",
                "month": 6,
                "year": 2026,
                "view": "monthly",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["data"]
        self.assertEqual(data["view"], "monthly")
        self.assertEqual(len(data["rows"]), 1)
        self.assertEqual(data["rows"][0]["item_description"], "Concrete")
        self.assertEqual(data["summary"]["tests_conducted"], 22)

    def test_client_report_cumulative(self):
        FrequencyChartEntry.objects.create(
            projectName="Thane Project",
            month=1,
            year=2026,
            sr_no=1,
            item_description="Steel",
            type_of_test="Tensile",
            unit="MT",
            qty_this_bill=Decimal("10"),
        )
        response = self.client.get(
            self.CHART_URL,
            {
                "format": "client",
                "project_name": "Thane Project",
                "month": 6,
                "year": 2026,
                "view": "cumulative",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["data"]["rows"]), 2)

    def test_register_create_with_master(self):
        payload = {
            "projectName": "Thane Project",
            "month": 7,
            "year": 2026,
            "item_description": "Concrete",
            "type_of_test": "Compressive Strength",
            "qty_previous_bill": 100,
            "qty_this_bill": 50,
        }
        response = self.client.post(self.REGISTER_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["data"]["sr_no"], 1)
        self.assertIn("frequency_master_id", response.data["data"])

    def test_project_quality_unchanged(self):
        response = self.client.get(
            "/api/project-quality/",
            {"project_name": "Thane Project", "month": 6, "year": 2026},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
