"""
Tests for Correspondence & Delivery Status (monthly CLIENT / CONTRACTOR tracking).
"""

from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from projects.models import Project

from .controllers.correspondence_metrics import (
    compute_delivery_efficiency,
    compute_pending_correspondence,
    metrics_from_counts,
)
from .models.correspondence import CorrespondenceStatus


class CorrespondenceMetricsTest(TestCase):
  def test_pending_never_negative(self):
    self.assertEqual(compute_pending_correspondence(100, 120), 0)

  def test_pending_normal(self):
    self.assertEqual(compute_pending_correspondence(120, 110), 10)

  def test_efficiency_zero_when_no_received(self):
    self.assertEqual(compute_delivery_efficiency(0, 0), 0.0)

  def test_efficiency_calculated(self):
    self.assertEqual(compute_delivery_efficiency(110, 120), 91.67)

  def test_metrics_from_counts(self):
    m = metrics_from_counts(120, 110)
    self.assertEqual(m["pending_correspondence"], 10)
    self.assertEqual(m["delivery_efficiency"], 91.67)


class CorrespondenceStatusModelTest(TestCase):
  def setUp(self):
    self.project = Project.objects.create(name="Model Test Project")

  def _make(self, **kwargs):
    defaults = {
      "project": self.project,
      "month": 6,
      "year": 2026,
      "correspondence_type": CorrespondenceStatus.TYPE_CLIENT,
      "correspondence_received": 100,
      "correspondence_delivered": 80,
    }
    defaults.update(kwargs)
    return CorrespondenceStatus.objects.create(**defaults)

  def test_unique_per_project_month_year_type(self):
    self._make()
    with self.assertRaises(Exception):
      self._make()

  def test_client_and_contractor_same_month_allowed(self):
    self._make(correspondence_type=CorrespondenceStatus.TYPE_CLIENT)
    self._make(correspondence_type=CorrespondenceStatus.TYPE_CONTRACTOR)
    self.assertEqual(CorrespondenceStatus.objects.count(), 2)

  def test_invalid_month_rejected(self):
    obj = CorrespondenceStatus(
      project=self.project,
      month=13,
      year=2026,
      correspondence_type=CorrespondenceStatus.TYPE_CLIENT,
    )
    with self.assertRaises(ValidationError):
      obj.save()

  def test_invalid_type_rejected(self):
    obj = CorrespondenceStatus(
      project=self.project,
      month=6,
      year=2026,
      correspondence_type="INVALID",
    )
    with self.assertRaises(ValidationError):
      obj.save()


class CorrespondenceAPITest(APITestCase):
  LIST_URL = "/api/correspondence/"

  def setUp(self):
    self.project = Project.objects.create(name="Thane Project")
    CorrespondenceStatus.objects.filter(project=self.project).delete()

  def _detail_url(self, pk):
    return f"/api/correspondence/{pk}/"

  def _monthly_url(self, month=6, year=2026):
    return f"/api/correspondence/project/Thane%20Project/month/{month}/year/{year}/"

  def _summary_url(self):
    return "/api/correspondence/project/Thane%20Project/summary/"

  def _yearly_url(self, year=2026):
    return f"/api/correspondence/project/Thane%20Project/year/{year}/summary/"

  def _dashboard_url(self):
    return "/api/correspondence/project/Thane%20Project/dashboard/"

  def _client_payload(self, received=120, delivered=110):
    return {
      "project_name": "Thane Project",
      "month": 6,
      "year": 2026,
      "correspondence_type": "CLIENT",
      "correspondence_received": received,
      "correspondence_delivered": delivered,
    }

  def _contractor_payload(self, received=90, delivered=70):
    return {
      "project_name": "Thane Project",
      "month": 6,
      "year": 2026,
      "correspondence_type": "CONTRACTOR",
      "correspondence_received": received,
      "correspondence_delivered": delivered,
    }

  def test_create_client_returns_201_with_metrics(self):
    response = self.client.post(self.LIST_URL, self._client_payload(), format="json")
    self.assertEqual(response.status_code, status.HTTP_201_CREATED)
    self.assertTrue(response.data["success"])
    data = response.data["data"]
    self.assertEqual(data["pending_correspondence"], 10)
    self.assertEqual(data["delivery_efficiency"], 91.67)

  def test_create_contractor(self):
    response = self.client.post(self.LIST_URL, self._contractor_payload(), format="json")
    self.assertEqual(response.status_code, status.HTTP_201_CREATED)

  def test_upsert_same_key_returns_200(self):
    self.client.post(self.LIST_URL, self._client_payload(), format="json")
    response = self.client.post(
      self.LIST_URL,
      self._client_payload(received=200, delivered=180),
      format="json",
    )
    self.assertEqual(response.status_code, status.HTTP_200_OK)
    self.assertEqual(
      CorrespondenceStatus.objects.filter(
        project=self.project,
        month=6,
        year=2026,
        correspondence_type=CorrespondenceStatus.TYPE_CLIENT,
      ).count(),
      1,
    )

  def test_monthly_endpoint_dual_type(self):
    self.client.post(self.LIST_URL, self._client_payload(), format="json")
    self.client.post(self.LIST_URL, self._contractor_payload(), format="json")
    response = self.client.get(self._monthly_url())
    self.assertEqual(response.status_code, status.HTTP_200_OK)
    data = response.data["data"]
    self.assertEqual(data["client"]["correspondence_received"], 120)
    self.assertEqual(data["contractor"]["pending_correspondence"], 20)

  def test_project_summary_aggregates(self):
    self.client.post(self.LIST_URL, self._client_payload(), format="json")
    self.client.post(
      self.LIST_URL,
      {**self._client_payload(), "month": 7, "correspondence_received": 30, "correspondence_delivered": 20},
      format="json",
    )
    response = self.client.get(self._summary_url())
    self.assertEqual(response.status_code, status.HTTP_200_OK)
    self.assertEqual(response.data["data"]["client"]["correspondence_received"], 150)

  def test_yearly_summary(self):
    self.client.post(self.LIST_URL, self._client_payload(), format="json")
    response = self.client.get(self._yearly_url())
    self.assertEqual(response.status_code, status.HTTP_200_OK)
    self.assertEqual(response.data["data"]["year"], 2026)

  def test_dashboard_structure(self):
    self.client.post(self.LIST_URL, self._client_payload(), format="json")
    response = self.client.get(self._dashboard_url())
    self.assertEqual(response.status_code, status.HTTP_200_OK)
    data = response.data["data"]
    self.assertIn("current_month", data)
    self.assertIn("project_summary", data)
    self.assertIn("client", data["current_month"])

  def test_list_filter_by_type(self):
    self.client.post(self.LIST_URL, self._client_payload(), format="json")
    self.client.post(self.LIST_URL, self._contractor_payload(), format="json")
    response = self.client.get(
      self.LIST_URL,
      {"correspondence_type": "CLIENT", "month": 6, "year": 2026},
    )
    self.assertEqual(response.status_code, status.HTTP_200_OK)
    results = response.data["data"].get("results", response.data["data"])
    self.assertEqual(len(results), 1)
    self.assertEqual(results[0]["correspondence_type"], "CLIENT")

  def test_retrieve_update_delete(self):
    create = self.client.post(self.LIST_URL, self._client_payload(), format="json")
    pk = create.data["data"]["id"]

    get_resp = self.client.get(self._detail_url(pk))
    self.assertEqual(get_resp.status_code, status.HTTP_200_OK)

    patch_resp = self.client.patch(
      self._detail_url(pk),
      {"correspondence_delivered": 115},
      format="json",
    )
    self.assertEqual(patch_resp.status_code, status.HTTP_200_OK)
    self.assertEqual(patch_resp.data["data"]["pending_correspondence"], 5)

    del_resp = self.client.delete(self._detail_url(pk))
    self.assertEqual(del_resp.status_code, status.HTTP_200_OK)
    self.assertFalse(CorrespondenceStatus.objects.filter(pk=pk).exists())

  def test_legacy_camelcase_post(self):
    payload = {
      "projectName": "Thane Project",
      "month": 6,
      "year": 2026,
      "correspondence_type": "CLIENT",
      "correspondenceReceived": 50,
      "correspondenceDelivered": 40,
    }
    response = self.client.post(self.LIST_URL, payload, format="json")
    self.assertEqual(response.status_code, status.HTTP_201_CREATED)
    self.assertEqual(response.data["data"]["correspondenceReceived"], 50)

  def test_rejects_invalid_month(self):
    payload = self._client_payload()
    payload["month"] = 13
    response = self.client.post(self.LIST_URL, payload, format="json")
    self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
