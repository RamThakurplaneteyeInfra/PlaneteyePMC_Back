"""
Tests for monthly project-wise correspondence document tracking.
"""

from datetime import date

from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from .controllers.correspondence_metrics import (
    compute_delivery_efficiency,
    metrics_from_counts,
    metrics_from_queryset,
)
from .models.correspondence import CorrespondenceDocument


class CorrespondenceMetricsTest(TestCase):
    def test_example_kpi_all_delivered_mixed(self):
        """Received=10, On Time=7, Late=3, Pending=0 -> Delivered=10, Eff=70%."""
        m = metrics_from_counts(received=10, on_time=7, late_deliveries=3, pending=0)
        self.assertEqual(m["received"], 10)
        self.assertEqual(m["delivered"], 10)
        self.assertEqual(m["pending"], 0)
        self.assertEqual(m["on_time"], 7)
        self.assertEqual(m["late_deliveries"], 3)
        self.assertEqual(m["delivery_efficiency"], 70.0)
        self.assertEqual(m["status_breakdown"], {
            "on_time": 7,
            "late_deliveries": 3,
            "pending": 0,
        })

    def test_pending_only(self):
        m = metrics_from_counts(received=5, on_time=0, late_deliveries=0, pending=5)
        self.assertEqual(m["delivered"], 0)
        self.assertEqual(m["pending"], 5)
        self.assertEqual(m["delivery_efficiency"], 0.0)

    def test_on_time_only(self):
        m = metrics_from_counts(received=4, on_time=4, late_deliveries=0, pending=0)
        self.assertEqual(m["delivered"], 4)
        self.assertEqual(m["delivery_efficiency"], 100.0)

    def test_late_counts_as_delivered_not_pending(self):
        """Late deliveries must increase delivered, not pending."""
        m = metrics_from_counts(received=3, on_time=0, late_deliveries=3, pending=0)
        self.assertEqual(m["delivered"], 3)
        self.assertEqual(m["pending"], 0)
        self.assertEqual(m["late_deliveries"], 3)
        self.assertEqual(m["delivery_efficiency"], 0.0)

    def test_efficiency_formula_on_time_over_delivered(self):
        self.assertEqual(compute_delivery_efficiency(7, 10), 70.0)
        self.assertEqual(compute_delivery_efficiency(0, 0), 0.0)

    def test_delivered_equals_on_time_plus_late(self):
        m = metrics_from_counts(received=8, on_time=5, late_deliveries=2, pending=1)
        self.assertEqual(m["delivered"], 7)
        self.assertEqual(m["on_time"] + m["late_deliveries"], m["delivered"])


class CorrespondenceDocumentModelTest(TestCase):
    def _make(self, **kwargs):
        defaults = {
            "project_name": "Model Test Project",
            "month": 6,
            "year": 2026,
            "correspondence_type": CorrespondenceDocument.TYPE_CLIENT,
            "sr_no": CorrespondenceDocument.next_sr_no(
                "Model Test Project",
                6,
                2026,
                CorrespondenceDocument.TYPE_CLIENT,
            ),
            "description": "Test doc",
            "received_date": date(2026, 6, 1),
        }
        defaults.update(kwargs)
        return CorrespondenceDocument.objects.create(**defaults)

    def test_deadline_and_status_on_time(self):
        doc = self._make(delivered_date=date(2026, 6, 5))
        self.assertEqual(doc.deadline_date, date(2026, 6, 8))
        self.assertEqual(doc.delivered_status, "DELIVERED_ON_TIME")

    def test_status_pending(self):
        doc = self._make()
        self.assertEqual(doc.delivered_status, "PENDING")

    def test_status_late(self):
        doc = self._make(delivered_date=date(2026, 6, 15))
        self.assertEqual(doc.delivered_status, "DELIVERED_LATE")

    def test_received_date_must_match_month_year(self):
        obj = CorrespondenceDocument(
            project_name="X",
            month=6,
            year=2026,
            correspondence_type=CorrespondenceDocument.TYPE_CLIENT,
            sr_no=1,
            description="bad",
            received_date=date(2026, 7, 1),
        )
        with self.assertRaises(ValidationError):
            obj.save()


class CorrespondenceQuerysetMetricsTest(TestCase):
    """Integration: metrics_from_queryset with real documents."""

    PROJECT = "Metrics Queryset Project"

    def setUp(self):
        CorrespondenceDocument.objects.filter(
            project_name=self.PROJECT
        ).delete()

    def _create(self, sr_no, delivered_date=None):
        return CorrespondenceDocument.objects.create(
            project_name=self.PROJECT,
            month=6,
            year=2026,
            correspondence_type=CorrespondenceDocument.TYPE_CLIENT,
            sr_no=sr_no,
            description=f"Doc {sr_no}",
            received_date=date(2026, 6, 1),
            delivered_date=delivered_date,
        )

    def test_mixed_scenario(self):
        self._create(1, date(2026, 6, 5))   # on time
        self._create(2, date(2026, 6, 5))   # on time
        self._create(3, date(2026, 6, 15))  # late
        self._create(4, None)               # pending

        qs = CorrespondenceDocument.objects.filter(project_name=self.PROJECT)
        m = metrics_from_queryset(qs)

        self.assertEqual(m["received"], 4)
        self.assertEqual(m["on_time"], 2)
        self.assertEqual(m["late_deliveries"], 1)
        self.assertEqual(m["delivered"], 3)
        self.assertEqual(m["pending"], 1)
        self.assertEqual(m["delivered"], m["on_time"] + m["late_deliveries"])
        self.assertAlmostEqual(m["delivery_efficiency"], round(2 / 3 * 100, 2))


class CorrespondenceDocumentAPITest(APITestCase):
    LIST_URL = "/api/correspondence-documents/"
    DASHBOARD_URL = "/api/correspondence-documents/dashboard/"

    def setUp(self):
        CorrespondenceDocument.objects.filter(
            project_name__iexact="Thane Project"
        ).delete()

    def _payload(self, correspondence_type="CLIENT", delivery_date="2026-06-05"):
        data = {
            "project_name": "Thane Project",
            "month": 6,
            "year": 2026,
            "correspondence_type": correspondence_type,
            "description": "Letter",
            "received_date": "2026-06-01",
        }
        if delivery_date:
            data["delivery_date"] = delivery_date
        return data

    def test_create_auto_sr_no(self):
        r1 = self.client.post(self.LIST_URL, self._payload(), format="json")
        r2 = self.client.post(
            self.LIST_URL,
            self._payload(delivery_date=None),
            format="json",
        )
        self.assertEqual(r1.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r2.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r1.data["data"]["delivered_status"], "DELIVERED_ON_TIME")

    def test_dashboard_kpi_late_counts_as_delivered(self):
        self.client.post(self.LIST_URL, self._payload(), format="json")
        self.client.post(
            self.LIST_URL,
            self._payload(delivery_date=None),
            format="json",
        )
        self.client.post(
            self.LIST_URL,
            self._payload(
                correspondence_type="CONTRACTOR",
                delivery_date="2026-06-20",
            ),
            format="json",
        )
        response = self.client.get(
            self.DASHBOARD_URL,
            {"project_name": "Thane Project", "month": 6, "year": 2026},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        client = response.data["data"]["client"]
        self.assertEqual(client["received"], 2)
        self.assertEqual(client["delivered"], 1)
        self.assertEqual(client["pending"], 1)
        self.assertEqual(client["on_time"], 1)
        self.assertEqual(client["late_deliveries"], 0)
        self.assertEqual(client["delivered"], client["on_time"] + client["late_deliveries"])
        self.assertEqual(client["status_breakdown"]["pending"], 1)

        contractor = response.data["data"]["contractor"]
        self.assertEqual(contractor["received"], 1)
        self.assertEqual(contractor["delivered"], 1)
        self.assertEqual(contractor["pending"], 0)
        self.assertEqual(contractor["on_time"], 0)
        self.assertEqual(contractor["late_deliveries"], 1)
        self.assertEqual(contractor["delivery_efficiency"], 0.0)

    def test_patch_late_delivery_updates_status(self):
        create = self.client.post(self.LIST_URL, self._payload(), format="json")
        pk = create.data["data"]["id"]
        patch = self.client.patch(
            f"{self.LIST_URL}{pk}/",
            {"delivery_date": "2026-06-15"},
            format="json",
        )
        self.assertEqual(patch.data["data"]["delivered_status"], "DELIVERED_LATE")

        response = self.client.get(
            self.DASHBOARD_URL,
            {"project_name": "Thane Project", "month": 6, "year": 2026},
        )
        client = response.data["data"]["client"]
        self.assertEqual(client["late_deliveries"], 1)
        self.assertEqual(client["delivered"], 1)
        self.assertEqual(client["pending"], 0)
