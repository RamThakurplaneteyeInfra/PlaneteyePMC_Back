"""
Tests for monthly project-wise correspondence document tracking.
"""

from datetime import date

from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from core.test_auth import authenticate_client

from .controllers.correspondence_metrics import (
    VIEW_CUMULATIVE,
    VIEW_MONTHLY,
    compute_delivery_efficiency,
    dashboard_response,
    filter_by_period,
    metrics_from_counts,
    metrics_from_queryset,
    period_date_range,
    scl_delivered_metrics,
)
from .controllers.correspondence_pending import compute_pending
from .models.correspondence import CorrespondenceDocument
from .models.inbound_summary import InboundCorrespondenceSummary
from .models.scl_delivered_summary import SCLDeliveredCorrespondenceSummary


class CorrespondenceMetricsTest(TestCase):
    def test_example_kpi_all_delivered_mixed(self):
        """Received=10, On Time=7, Late=3, Record=0 -> Delivered=10, Pending=0, Eff=70%."""
        m = metrics_from_counts(received=10, on_time=7, late_deliveries=3, record=0)
        self.assertEqual(m["received"], 10)
        self.assertEqual(m["delivered"], 10)
        self.assertEqual(m["pending"], 0)
        self.assertEqual(m["record"], 0)
        self.assertEqual(m["on_time"], 7)
        self.assertEqual(m["late_deliveries"], 3)
        self.assertEqual(m["delivery_efficiency"], 70.0)

    def test_pending_with_record(self):
        """Received=10, Delivered=6, Record=2 -> Pending=2."""
        m = metrics_from_counts(received=10, on_time=6, late_deliveries=0, record=2)
        self.assertEqual(m["pending"], 2)
        self.assertEqual(m["record"], 2)

    def test_pending_record_zero(self):
        m = metrics_from_counts(received=20, on_time=15, late_deliveries=0, record=5)
        self.assertEqual(m["pending"], 0)

    def test_pending_record_floors_at_zero(self):
        m = metrics_from_counts(received=10, on_time=8, late_deliveries=0, record=5)
        self.assertEqual(m["pending"], 0)

    def test_compute_pending_helper(self):
        self.assertEqual(compute_pending(10, 6, 2), 2)
        self.assertEqual(compute_pending(20, 15, 5), 0)
        self.assertEqual(compute_pending(12, 4, 1), 7)
        self.assertEqual(compute_pending(10, 18, 0), 0)

    def test_pending_only(self):
        m = metrics_from_counts(received=5, on_time=0, late_deliveries=0, record=0)
        self.assertEqual(m["delivered"], 0)
        self.assertEqual(m["pending"], 5)
        self.assertEqual(m["delivery_efficiency"], 0.0)

    def test_on_time_only(self):
        m = metrics_from_counts(received=4, on_time=4, late_deliveries=0, record=0)
        self.assertEqual(m["delivered"], 4)
        self.assertEqual(m["delivery_efficiency"], 100.0)

    def test_late_counts_as_delivered_not_pending(self):
        """Late deliveries must increase delivered, not pending."""
        m = metrics_from_counts(received=3, on_time=0, late_deliveries=3, record=0)
        self.assertEqual(m["delivered"], 3)
        self.assertEqual(m["pending"], 0)
        self.assertEqual(m["late_deliveries"], 3)
        self.assertEqual(m["delivery_efficiency"], 0.0)

    def test_efficiency_formula_on_time_over_delivered(self):
        self.assertEqual(compute_delivery_efficiency(7, 10), 70.0)
        self.assertEqual(compute_delivery_efficiency(0, 0), 0.0)

    def test_delivered_equals_on_time_plus_late(self):
        m = metrics_from_counts(received=8, on_time=5, late_deliveries=2, record=1)
        self.assertEqual(m["delivered"], 7)
        self.assertEqual(m["pending"], 0)
        self.assertEqual(m["on_time"] + m["late_deliveries"], m["delivered"])

    def test_period_date_range_cumulative(self):
        from_date, to_date = period_date_range(2026, 6, VIEW_CUMULATIVE)
        self.assertEqual(from_date.isoformat(), "2026-01-01")
        self.assertEqual(to_date.isoformat(), "2026-06-30")

    def test_period_date_range_monthly(self):
        from_date, to_date = period_date_range(2026, 6, VIEW_MONTHLY)
        self.assertEqual(from_date.isoformat(), "2026-06-01")
        self.assertEqual(to_date.isoformat(), "2026-06-30")


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
    SCL_URL = "/api/correspondence-documents/scl-delivered-correspondence/"
    INBOUND_URL = "/api/correspondence-documents/inbound-correspondence/"

    def _scl_payload(self, **overrides):
        data = {
            "project_name": "Thane Project",
            "month": 6,
            "year": 2026,
            "view": "cumulative",
            "client_received": 2,
            "client_delivered": 1,
            "client_record": 0,
            "contractor_received": 3,
            "contractor_delivered": 1,
            "contractor_record": 0,
            "other_agency_received": 4,
            "other_agency_delivered": 1,
            "other_agency_record": 0,
        }
        data.update(overrides)
        return data

    def _inbound_payload(self, **overrides):
        data = {
            "project_name": "Thane Project",
            "month": 6,
            "year": 2026,
            "view": "monthly",
            "client_received": 10,
            "client_delivered": 6,
            "client_record": 2,
            "contractor_received": 12,
            "contractor_delivered": 8,
            "contractor_record": 1,
        }
        data.update(overrides)
        return data

    def setUp(self):
        CorrespondenceDocument.objects.filter(
            project_name__iexact="Thane Project"
        ).delete()
        SCLDeliveredCorrespondenceSummary.objects.filter(
            project_name__iexact="Thane Project"
        ).delete()
        InboundCorrespondenceSummary.objects.filter(
            project_name__iexact="Thane Project"
        ).delete()
        authenticate_client(self.client)

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

    def test_dashboard_monthly_includes_view_metadata(self):
        self.client.post(self.LIST_URL, self._payload(), format="json")
        response = self.client.get(
            self.DASHBOARD_URL,
            {"project_name": "Thane Project", "month": 6, "year": 2026},
        )
        data = response.data["data"]
        self.assertEqual(data["view"], "monthly")
        self.assertEqual(data["from_date"], "2026-06-01")
        self.assertEqual(data["to_date"], "2026-06-30")
        self.assertIn("scl_delivered_correspondence", data)
        self.assertIn("recent_documents", data)

    def test_dashboard_cumulative_aggregates_year_to_date(self):
        CorrespondenceDocument.objects.filter(
            project_name__iexact="Thane Project"
        ).delete()
        self.client.post(
            self.LIST_URL,
            {
                **self._payload(delivery_date="2026-01-05"),
                "month": 1,
                "year": 2026,
                "received_date": "2026-01-01",
            },
            format="json",
        )
        self.client.post(self.LIST_URL, self._payload(), format="json")

        response = self.client.get(
            self.DASHBOARD_URL,
            {
                "project_name": "Thane Project",
                "month": 6,
                "year": 2026,
                "view": "cumulative",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["data"]
        self.assertEqual(data["view"], "cumulative")
        self.assertEqual(data["from_date"], "2026-01-01")
        self.assertEqual(data["client"]["received"], 2)

    def test_scl_delivered_correspondence_counts(self):
        CorrespondenceDocument.objects.filter(
            project_name__iexact="Thane Project"
        ).delete()
        CorrespondenceDocument.objects.create(
            project_name="Thane Project",
            month=6,
            year=2026,
            correspondence_type=CorrespondenceDocument.TYPE_CLIENT,
            flow_direction=CorrespondenceDocument.FLOW_OUTBOUND_SCL,
            sender=CorrespondenceDocument.SENDER_SCL,
            recipient_type=CorrespondenceDocument.RECIPIENT_CLIENT,
            sr_no=1,
            description="SCL to client",
            received_date=date(2026, 6, 1),
            delivered_date=date(2026, 6, 3),
        )
        CorrespondenceDocument.objects.create(
            project_name="Thane Project",
            month=6,
            year=2026,
            correspondence_type=CorrespondenceDocument.TYPE_CONTRACTOR,
            flow_direction=CorrespondenceDocument.FLOW_OUTBOUND_SCL,
            sender=CorrespondenceDocument.SENDER_SCL,
            recipient_type=CorrespondenceDocument.RECIPIENT_CONTRACTOR,
            sr_no=1,
            description="SCL to contractor",
            received_date=date(2026, 6, 2),
            delivered_date=date(2026, 6, 4),
        )
        period_qs = filter_by_period(
            CorrespondenceDocument.objects.all(),
            project_name="Thane Project",
            month=6,
            year=2026,
        )
        scl = scl_delivered_metrics(period_qs)
        self.assertEqual(scl["client"]["received"], 1)
        self.assertEqual(scl["client"]["delivered"], 1)
        self.assertEqual(scl["client"]["pending"], 0)
        self.assertEqual(scl["contractor"]["received"], 1)
        self.assertEqual(scl["contractor"]["delivered"], 1)
        self.assertEqual(scl["total"], 2)

        dashboard = dashboard_response(
            "Thane Project", 6, 2026, period_qs, view=VIEW_MONTHLY
        )
        self.assertEqual(
            dashboard["scl_delivered_correspondence"]["totals"]["delivered"], 2
        )
        self.assertEqual(len(dashboard["recent_documents"]), 2)

    def test_scl_delivered_post_creates_summary(self):
        response = self.client.post(
            self.SCL_URL, self._scl_payload(), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        scl = response.data["data"]["scl_delivered_correspondence"]
        self.assertEqual(scl["client"]["received"], 2)
        self.assertEqual(scl["client"]["delivered"], 1)
        self.assertEqual(scl["client"]["record"], 0)
        self.assertEqual(scl["client"]["pending"], 1)
        self.assertEqual(scl["contractor"]["received"], 3)
        self.assertEqual(scl["contractor"]["delivered"], 1)
        self.assertEqual(scl["contractor"]["pending"], 2)
        self.assertEqual(scl["other_agency"]["received"], 4)
        self.assertEqual(scl["other_agency"]["delivered"], 1)
        self.assertEqual(scl["other_agency"]["pending"], 3)
        self.assertEqual(scl["totals"]["received"], 9)
        self.assertEqual(scl["totals"]["delivered"], 3)
        self.assertEqual(scl["totals"]["record"], 0)
        self.assertEqual(scl["totals"]["pending"], 6)
        self.assertEqual(scl["total"], 3)

    def test_scl_delivered_post_upsert_then_patch(self):
        self.client.post(self.SCL_URL, self._scl_payload(), format="json")
        patch = self.client.patch(
            self.SCL_URL,
            self._scl_payload(client_delivered=5),
            format="json",
        )
        self.assertEqual(patch.status_code, status.HTTP_200_OK)
        self.assertEqual(
            patch.data["data"]["scl_delivered_correspondence"]["client"]["delivered"], 5
        )
        self.assertEqual(
            patch.data["data"]["scl_delivered_correspondence"]["client"]["pending"], 0
        )

    def test_scl_delivered_post_via_dashboard(self):
        response = self.client.post(
            self.DASHBOARD_URL, self._scl_payload(), format="json"
        )
        self.assertIn(
            response.status_code,
            (status.HTTP_200_OK, status.HTTP_201_CREATED),
        )
        self.assertEqual(
            response.data["data"]["scl_delivered_correspondence"]["totals"]["delivered"], 3
        )

    def test_scl_delivered_post_via_short_url(self):
        """Frontend posts to /scl-delivered/ (not scl-delivered-correspondence/)."""
        response = self.client.post(
            "/api/correspondence-documents/scl-delivered/",
            self._scl_payload(),
            format="json",
        )
        self.assertIn(
            response.status_code,
            (status.HTTP_200_OK, status.HTTP_201_CREATED),
        )
        self.assertEqual(
            response.data["data"]["scl_delivered_correspondence"]["totals"]["delivered"], 3
        )

    def test_dashboard_returns_saved_scl_summary(self):
        self.client.post(self.SCL_URL, self._scl_payload(), format="json")
        self.client.post(self.LIST_URL, self._payload(), format="json")
        response = self.client.get(
            self.DASHBOARD_URL,
            {
                "project_name": "Thane Project",
                "month": 6,
                "year": 2026,
                "view": "cumulative",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        scl = response.data["data"]["scl_delivered_correspondence"]
        self.assertEqual(scl["totals"]["received"], 9)
        self.assertEqual(scl["totals"]["delivered"], 3)
        self.assertEqual(scl["totals"]["record"], 0)
        self.assertEqual(scl["totals"]["pending"], 6)

    def test_scl_pending_when_received_exceeds_delivered(self):
        response = self.client.post(
            self.SCL_URL,
            self._scl_payload(client_received=25, client_delivered=18),
            format="json",
        )
        scl = response.data["data"]["scl_delivered_correspondence"]
        self.assertEqual(scl["client"]["pending"], 7)

    def test_scl_pending_when_received_equals_delivered(self):
        response = self.client.post(
            self.SCL_URL,
            self._scl_payload(client_received=18, client_delivered=18),
            format="json",
        )
        scl = response.data["data"]["scl_delivered_correspondence"]
        self.assertEqual(scl["client"]["pending"], 0)

    def test_scl_pending_never_negative_when_delivered_exceeds_received(self):
        response = self.client.post(
            self.SCL_URL,
            self._scl_payload(client_received=10, client_delivered=18),
            format="json",
        )
        scl = response.data["data"]["scl_delivered_correspondence"]
        self.assertEqual(scl["client"]["pending"], 0)

    def test_scl_null_values_are_treated_as_zero(self):
        response = self.client.post(
            self.SCL_URL,
            self._scl_payload(
                client_received=None,
                client_delivered=None,
                contractor_received=None,
                contractor_delivered=None,
                other_agency_received=None,
                other_agency_delivered=None,
            ),
            format="json",
        )
        scl = response.data["data"]["scl_delivered_correspondence"]
        self.assertEqual(scl["client"], {"received": 0, "delivered": 0, "record": 0, "pending": 0})
        self.assertEqual(scl["totals"], {"received": 0, "delivered": 0, "record": 0, "pending": 0})

    def test_scl_nested_payload_and_total_calculations(self):
        response = self.client.post(
            self.SCL_URL,
            {
                "project_name": "Thane Project",
                "month": 6,
                "year": 2026,
                "scl_delivered_correspondence": {
                    "client": {"received": 25, "delivered": 18},
                    "contractor": {"received": 40, "delivered": 30},
                    "other_agency": {"received": 15, "delivered": 10},
                },
            },
            format="json",
        )
        scl = response.data["data"]["scl_delivered_correspondence"]
        self.assertEqual(scl["client"], {"received": 25, "delivered": 18, "record": 0, "pending": 7})
        self.assertEqual(
            scl["contractor"],
            {"received": 40, "delivered": 30, "record": 0, "pending": 10},
        )
        self.assertEqual(
            scl["other_agency"],
            {"received": 15, "delivered": 10, "record": 0, "pending": 5},
        )
        self.assertEqual(
            scl["totals"],
            {"received": 80, "delivered": 58, "record": 0, "pending": 22},
        )


class InboundCorrespondenceRecordTest(TestCase):
    def test_pending_with_record(self):
        summary = InboundCorrespondenceSummary(
            project_name="P",
            month=6,
            year=2026,
            client_received=10,
            client_delivered=6,
            client_record=2,
        )
        block = summary.client_metrics()
        self.assertEqual(block["pending"], 2)
        self.assertEqual(block["record"], 2)

    def test_pending_floors_at_zero(self):
        summary = InboundCorrespondenceSummary(
            project_name="P",
            month=6,
            year=2026,
            contractor_received=10,
            contractor_delivered=8,
            contractor_record=5,
        )
        self.assertEqual(summary.contractor_metrics()["pending"], 0)


class SCLRecordAPITest(APITestCase):
    SCL_URL = "/api/correspondence-documents/scl-delivered-correspondence/"

    def setUp(self):
        SCLDeliveredCorrespondenceSummary.objects.filter(
            project_name__iexact="Thane Project"
        ).delete()
        authenticate_client(self.client)

    def test_scl_pending_with_record(self):
        response = self.client.post(
            self.SCL_URL,
            {
                "project_name": "Thane Project",
                "month": 6,
                "year": 2026,
                "client_received": 10,
                "client_delivered": 6,
                "client_record": 2,
                "contractor_received": 20,
                "contractor_delivered": 15,
                "contractor_record": 5,
                "other_agency_received": 8,
                "other_agency_delivered": 4,
                "other_agency_record": 1,
            },
            format="json",
        )
        scl = response.data["data"]["scl_delivered_correspondence"]
        self.assertEqual(scl["client"]["pending"], 2)
        self.assertEqual(scl["contractor"]["pending"], 0)
        self.assertEqual(scl["other_agency"]["pending"], 3)
        self.assertEqual(scl["totals"]["record"], 8)
        self.assertEqual(scl["totals"]["pending"], 5)

    def test_scl_record_cannot_exceed_received(self):
        response = self.client.post(
            self.SCL_URL,
            {
                "project_name": "Thane Project",
                "month": 6,
                "year": 2026,
                "client_received": 5,
                "client_delivered": 2,
                "client_record": 6,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("client_record", response.data["errors"])


class InboundCorrespondenceAPITest(APITestCase):
    INBOUND_URL = "/api/correspondence-documents/inbound-correspondence/"
    DASHBOARD_URL = "/api/correspondence-documents/dashboard/"

    def setUp(self):
        InboundCorrespondenceSummary.objects.filter(
            project_name__iexact="Thane Project"
        ).delete()
        CorrespondenceDocument.objects.filter(
            project_name__iexact="Thane Project"
        ).delete()
        authenticate_client(self.client)

    def test_inbound_post_returns_record_and_pending(self):
        response = self.client.post(
            self.INBOUND_URL,
            {
                "project_name": "Thane Project",
                "month": 6,
                "year": 2026,
                "client_received": 10,
                "client_delivered": 6,
                "client_record": 2,
                "contractor_received": 12,
                "contractor_delivered": 8,
                "contractor_record": 1,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.data["data"]
        self.assertEqual(data["client"]["record"], 2)
        self.assertEqual(data["client"]["pending"], 2)
        self.assertEqual(data["contractor"]["record"], 1)
        self.assertEqual(data["contractor"]["pending"], 3)

    def test_dashboard_uses_inbound_summary(self):
        self.client.post(
            self.INBOUND_URL,
            {
                "project_name": "Thane Project",
                "month": 6,
                "year": 2026,
                "client_received": 20,
                "client_delivered": 15,
                "client_record": 4,
                "contractor_received": 18,
                "contractor_delivered": 12,
                "contractor_record": 2,
            },
            format="json",
        )
        CorrespondenceDocument.objects.create(
            project_name="Thane Project",
            month=6,
            year=2026,
            correspondence_type=CorrespondenceDocument.TYPE_CLIENT,
            sr_no=1,
            description="Doc",
            received_date=date(2026, 6, 1),
        )
        response = self.client.get(
            self.DASHBOARD_URL,
            {"project_name": "Thane Project", "month": 6, "year": 2026},
        )
        client = response.data["data"]["client"]
        self.assertEqual(client["received"], 20)
        self.assertEqual(client["delivered"], 15)
        self.assertEqual(client["record"], 4)
        self.assertEqual(client["pending"], 1)
        contractor = response.data["data"]["contractor"]
        self.assertEqual(contractor["pending"], 4)

    def test_inbound_nested_payload(self):
        response = self.client.post(
            self.INBOUND_URL,
            {
                "project_name": "Thane Project",
                "month": 6,
                "year": 2026,
                "client": {"received": 12, "delivered": 4, "record": 1},
                "contractor": {"received": 8, "delivered": 5, "record": 0},
            },
            format="json",
        )
        data = response.data["data"]
        self.assertEqual(data["client"]["pending"], 7)
        self.assertEqual(data["contractor"]["pending"], 3)


class InboundCorrespondenceRecordTest(TestCase):
    def test_pending_with_record(self):
        summary = InboundCorrespondenceSummary(
            project_name="P",
            month=6,
            year=2026,
            client_received=10,
            client_delivered=6,
            client_record=2,
        )
        block = summary.client_metrics()
        self.assertEqual(block["pending"], 2)
        self.assertEqual(block["record"], 2)

    def test_pending_floors_at_zero(self):
        summary = InboundCorrespondenceSummary(
            project_name="P",
            month=6,
            year=2026,
            contractor_received=10,
            contractor_delivered=8,
            contractor_record=5,
        )
        self.assertEqual(summary.contractor_metrics()["pending"], 0)


class SCLRecordAPITest(APITestCase):
    SCL_URL = "/api/correspondence-documents/scl-delivered-correspondence/"

    def setUp(self):
        SCLDeliveredCorrespondenceSummary.objects.filter(
            project_name__iexact="Thane Project"
        ).delete()
        authenticate_client(self.client)

    def test_scl_pending_with_record(self):
        response = self.client.post(
            self.SCL_URL,
            {
                "project_name": "Thane Project",
                "month": 6,
                "year": 2026,
                "client_received": 10,
                "client_delivered": 6,
                "client_record": 2,
                "contractor_received": 20,
                "contractor_delivered": 15,
                "contractor_record": 5,
                "other_agency_received": 8,
                "other_agency_delivered": 4,
                "other_agency_record": 1,
            },
            format="json",
        )
        scl = response.data["data"]["scl_delivered_correspondence"]
        self.assertEqual(scl["client"]["pending"], 2)
        self.assertEqual(scl["contractor"]["pending"], 0)
        self.assertEqual(scl["other_agency"]["pending"], 3)
        self.assertEqual(scl["totals"]["record"], 8)
        self.assertEqual(scl["totals"]["pending"], 5)

    def test_scl_record_cannot_exceed_received(self):
        response = self.client.post(
            self.SCL_URL,
            {
                "project_name": "Thane Project",
                "month": 6,
                "year": 2026,
                "client_received": 5,
                "client_delivered": 2,
                "client_record": 6,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("client_record", response.data["errors"])


class InboundCorrespondenceAPITest(APITestCase):
    INBOUND_URL = "/api/correspondence-documents/inbound-correspondence/"
    DASHBOARD_URL = "/api/correspondence-documents/dashboard/"

    def setUp(self):
        InboundCorrespondenceSummary.objects.filter(
            project_name__iexact="Thane Project"
        ).delete()
        CorrespondenceDocument.objects.filter(
            project_name__iexact="Thane Project"
        ).delete()
        authenticate_client(self.client)

    def test_inbound_post_returns_record_and_pending(self):
        response = self.client.post(
            self.INBOUND_URL,
            {
                "project_name": "Thane Project",
                "month": 6,
                "year": 2026,
                "client_received": 10,
                "client_delivered": 6,
                "client_record": 2,
                "contractor_received": 12,
                "contractor_delivered": 8,
                "contractor_record": 1,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.data["data"]
        self.assertEqual(data["client"]["record"], 2)
        self.assertEqual(data["client"]["pending"], 2)
        self.assertEqual(data["contractor"]["record"], 1)
        self.assertEqual(data["contractor"]["pending"], 3)

    def test_dashboard_uses_inbound_summary(self):
        self.client.post(
            self.INBOUND_URL,
            {
                "project_name": "Thane Project",
                "month": 6,
                "year": 2026,
                "client_received": 20,
                "client_delivered": 15,
                "client_record": 4,
                "contractor_received": 18,
                "contractor_delivered": 12,
                "contractor_record": 2,
            },
            format="json",
        )
        CorrespondenceDocument.objects.create(
            project_name="Thane Project",
            month=6,
            year=2026,
            correspondence_type=CorrespondenceDocument.TYPE_CLIENT,
            sr_no=1,
            description="Doc",
            received_date=date(2026, 6, 1),
        )
        response = self.client.get(
            self.DASHBOARD_URL,
            {"project_name": "Thane Project", "month": 6, "year": 2026},
        )
        client = response.data["data"]["client"]
        self.assertEqual(client["received"], 20)
        self.assertEqual(client["delivered"], 15)
        self.assertEqual(client["record"], 4)
        self.assertEqual(client["pending"], 1)
        contractor = response.data["data"]["contractor"]
        self.assertEqual(contractor["pending"], 4)

    def test_inbound_nested_payload(self):
        response = self.client.post(
            self.INBOUND_URL,
            {
                "project_name": "Thane Project",
                "month": 6,
                "year": 2026,
                "client": {"received": 12, "delivered": 4, "record": 1},
                "contractor": {"received": 8, "delivered": 5, "record": 0},
            },
            format="json",
        )
        data = response.data["data"]
        self.assertEqual(data["client"]["pending"], 7)
        self.assertEqual(data["contractor"]["pending"], 3)
