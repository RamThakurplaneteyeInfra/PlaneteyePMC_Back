"""Tests for frequency chart client report and manual testing metrics."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from core.test_auth import authenticate_client

from .controllers.frequency_chart_report import (
    aggregate_testing_metrics,
    build_client_row,
    filter_frequency_chart_queryset,
    required_tests_for_quantity,
)
from .controllers.frequency_chart_serializer import FrequencyChartEntrySerializer
from .models.frequency_chart import (
    STATUS_COMPLETED,
    STATUS_COMPLETED_WITH_FAILURES,
    STATUS_SHORTFALL,
    FrequencyChartEntry,
    TestFrequencyMaster,
    compute_failed_tests,
    compute_shortfall,
    compute_testing_status,
)
from .models.project_quality_status import ProjectQualityStatus


class FrequencyChartCalculationTest(TestCase):
    def test_required_tests_from_frequency(self):
        self.assertEqual(required_tests_for_quantity(500, 1, 30), 17)
        self.assertEqual(required_tests_for_quantity(150, 1, 30), 5)
        self.assertEqual(required_tests_for_quantity(0, 1, 30), 0)
        self.assertIsNone(required_tests_for_quantity(100, None, None))

    def test_failed_and_shortfall_helpers(self):
        self.assertEqual(compute_failed_tests(8, 7), 1)
        self.assertEqual(compute_failed_tests(5, 8), 0)
        self.assertEqual(compute_shortfall(10, 8), 2)
        self.assertEqual(compute_shortfall(5, 8), 0)

    def test_status_calculation(self):
        self.assertEqual(compute_testing_status(10, 10, 10), STATUS_COMPLETED)
        self.assertEqual(
            compute_testing_status(10, 10, 8),
            STATUS_COMPLETED_WITH_FAILURES,
        )
        self.assertEqual(compute_testing_status(10, 8, 7), STATUS_SHORTFALL)

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
            required_tests=10,
            conducted_tests=8,
            passed_tests=7,
            remarks="Complied",
        )
        row = build_client_row(entry)
        self.assertEqual(row["required_tests_previous_bill"], 17)
        self.assertEqual(row["required_tests_this_bill"], 5)
        self.assertEqual(row["required_tests_upto_date"], 22)
        self.assertEqual(row["total_tests_conducted"], 22)
        self.assertEqual(row["total_qty"], 650.0)
        self.assertEqual(row["required_tests"], 10)
        self.assertEqual(row["conducted_tests"], 8)
        self.assertEqual(row["passed_tests"], 7)
        self.assertEqual(row["failed_tests"], 1)
        self.assertEqual(row["shortfall"], 2)
        self.assertEqual(row["status"], STATUS_SHORTFALL)

    def test_model_rejects_passed_gt_conducted(self):
        with self.assertRaises(ValidationError):
            FrequencyChartEntry.objects.create(
                projectName="Thane Project",
                month=6,
                year=2026,
                sr_no=1,
                item_description="Concrete",
                type_of_test="Compressive Strength",
                required_tests=10,
                conducted_tests=5,
                passed_tests=6,
            )

    def test_model_rejects_conducted_gt_required(self):
        with self.assertRaises(ValidationError):
            FrequencyChartEntry.objects.create(
                projectName="Thane Project",
                month=6,
                year=2026,
                sr_no=1,
                item_description="Concrete",
                type_of_test="Compressive Strength",
                required_tests=5,
                conducted_tests=6,
                passed_tests=5,
            )


class FrequencyChartSerializerMetricsTest(TestCase):
    def test_serializer_output_includes_computed_fields(self):
        entry = FrequencyChartEntry.objects.create(
            projectName="Thane Project",
            month=7,
            year=2026,
            sr_no=1,
            item_description="Concrete",
            type_of_test="Compressive Strength",
            unit="Cum",
            required_tests=10,
            conducted_tests=10,
            passed_tests=8,
        )
        data = FrequencyChartEntrySerializer(entry).data
        self.assertEqual(data["required_tests"], 10)
        self.assertEqual(data["conducted_tests"], 10)
        self.assertEqual(data["passed_tests"], 8)
        self.assertEqual(data["failed_tests"], 2)
        self.assertEqual(data["shortfall"], 0)
        self.assertEqual(data["status"], STATUS_COMPLETED_WITH_FAILURES)


def _error_fields(errors) -> set[str]:
    """Support both dict and list-of-{field,message} error shapes."""
    if isinstance(errors, dict):
        return set(errors.keys())
    if isinstance(errors, list):
        return {item.get("field") for item in errors if isinstance(item, dict)}
    return set()


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
            required_tests=22,
            conducted_tests=22,
            passed_tests=22,
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
        self.assertEqual(data["summary"]["required"], 22)
        self.assertEqual(data["summary"]["conducted"], 22)
        self.assertEqual(data["summary"]["passed"], 22)
        self.assertEqual(data["summary"]["failed"], 0)
        self.assertEqual(data["summary"]["shortfall"], 0)
        self.assertEqual(data["rows"][0]["status"], STATUS_COMPLETED)

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
            required_tests=10,
            conducted_tests=8,
            passed_tests=7,
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
        summary = response.data["data"]["summary"]
        self.assertEqual(summary["required"], 32)
        self.assertEqual(summary["conducted"], 30)
        self.assertEqual(summary["passed"], 29)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["shortfall"], 2)

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
        self.assertEqual(response.data["data"]["required_tests"], 0)
        self.assertEqual(response.data["data"]["failed_tests"], 0)
        self.assertEqual(response.data["data"]["shortfall"], 0)

    def test_register_create_with_manual_metrics(self):
        payload = {
            "projectName": "Thane Project",
            "month": 7,
            "year": 2026,
            "item_description": "Concrete",
            "type_of_test": "Compressive Strength",
            "required_tests": 10,
            "conducted_tests": 8,
            "passed_tests": 7,
        }
        response = self.client.post(self.REGISTER_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.data["data"]
        self.assertEqual(data["required_tests"], 10)
        self.assertEqual(data["conducted_tests"], 8)
        self.assertEqual(data["passed_tests"], 7)
        self.assertEqual(data["failed_tests"], 1)
        self.assertEqual(data["shortfall"], 2)
        self.assertEqual(data["status"], STATUS_SHORTFALL)

    def test_register_update_recalculates_metrics(self):
        entry = FrequencyChartEntry.objects.get(projectName="Thane Project", month=6)
        response = self.client.patch(
            f"{self.REGISTER_URL}{entry.id}/",
            {"conducted_tests": 20, "passed_tests": 18},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["data"]
        self.assertEqual(data["conducted_tests"], 20)
        self.assertEqual(data["passed_tests"], 18)
        self.assertEqual(data["failed_tests"], 2)
        self.assertEqual(data["shortfall"], 2)
        self.assertEqual(data["status"], STATUS_SHORTFALL)

    def test_register_validation_passed_gt_conducted(self):
        payload = {
            "projectName": "Thane Project",
            "month": 8,
            "year": 2026,
            "item_description": "Concrete",
            "type_of_test": "Compressive Strength",
            "required_tests": 10,
            "conducted_tests": 5,
            "passed_tests": 6,
        }
        response = self.client.post(self.REGISTER_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("passed_tests", _error_fields(response.data["errors"]))

    def test_register_validation_conducted_gt_required(self):
        payload = {
            "projectName": "Thane Project",
            "month": 8,
            "year": 2026,
            "item_description": "Concrete",
            "type_of_test": "Compressive Strength",
            "required_tests": 5,
            "conducted_tests": 8,
            "passed_tests": 7,
        }
        response = self.client.post(self.REGISTER_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("conducted_tests", _error_fields(response.data["errors"]))

    def test_dashboard_totals_from_aggregate(self):
        qs = filter_frequency_chart_queryset(
            project_name="Thane Project",
            month=6,
            year=2026,
            view="monthly",
        )
        summary = aggregate_testing_metrics(qs)
        self.assertEqual(summary["required"], 22)
        self.assertEqual(summary["conducted"], 22)
        self.assertEqual(summary["passed"], 22)
        self.assertEqual(summary["failed"], 0)
        self.assertEqual(summary["shortfall"], 0)

    def test_project_quality_unchanged(self):
        response = self.client.get(
            "/api/project-quality/",
            {"project_name": "Thane Project", "month": 6, "year": 2026},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
