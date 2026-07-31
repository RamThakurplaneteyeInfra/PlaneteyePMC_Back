"""
Tests for bottleneck register API.
"""

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from core.test_auth import authenticate_client
from projects.models import Project

from .metrics import compute_summary
from .models import Bottleneck

User = get_user_model()

LIST_URL = "/api/bottlenecks/"
SUMMARY_URL = "/api/bottlenecks/summary/"


class BottleneckMetricsTest(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name="Metrics Test Project")
        self.user = User.objects.create_user(username="bn_metrics", password="pass12345")

    def _create(self, **kwargs):
        defaults = {
            "project": self.project,
            "type": Bottleneck.TYPE_ISSUE,
            "description": "Test item",
            "priority": Bottleneck.PRIORITY_MEDIUM,
            "status": Bottleneck.STATUS_OPEN,
            "created_by": self.user,
        }
        defaults.update(kwargs)
        return Bottleneck.objects.create(**defaults)

    def test_summary_counts_by_type_and_status(self):
        self._create(type=Bottleneck.TYPE_ISSUE)
        self._create(type=Bottleneck.TYPE_ISSUE)
        self._create(type=Bottleneck.TYPE_CONCERN)
        self._create(type=Bottleneck.TYPE_RISK)
        self._create(type=Bottleneck.TYPE_ACTION, status=Bottleneck.STATUS_IN_PROGRESS)
        self._create(type=Bottleneck.TYPE_ACTION, status=Bottleneck.STATUS_CLOSED)

        summary = compute_summary(Bottleneck.objects.filter(project=self.project))
        self.assertEqual(summary["total_issues"], 2)
        self.assertEqual(summary["total_concerns"], 1)
        self.assertEqual(summary["total_risks"], 1)
        self.assertEqual(summary["total_actions"], 2)
        self.assertEqual(summary["open_items"], 4)
        self.assertEqual(summary["in_progress_items"], 1)
        self.assertEqual(summary["closed_items"], 1)

    def test_overdue_excludes_closed(self):
        yesterday = date.today() - timedelta(days=1)
        open_item = self._create(
            type=Bottleneck.TYPE_RISK,
            status=Bottleneck.STATUS_OPEN,
        )
        closed_item = self._create(
            type=Bottleneck.TYPE_RISK,
            status=Bottleneck.STATUS_CLOSED,
        )
        Bottleneck.objects.filter(pk__in=[open_item.pk, closed_item.pk]).update(
            target_date=yesterday
        )
        summary = compute_summary(Bottleneck.objects.filter(project=self.project))
        self.assertEqual(summary["overdue_items"], 1)


class BottleneckAPITest(APITestCase):
    def setUp(self):
        self.user = authenticate_client(self.client)
        self.assignee = User.objects.create_user(
            username="bn_assignee",
            password="pass12345",
            first_name="Site",
            last_name="Engineer",
        )
        self.project = Project.objects.create(
            name="Bottleneck API Project",
            status="active",
            team_lead=self.user,
        )

    def _payload(self, **overrides):
        data = {
            "project_id": self.project.id,
            "type": "RISK",
            "description": "Heavy rainfall may impact construction activities",
            "priority": "HIGH",
            "status": "OPEN",
            "assigned_to": self.assignee.id,
            "target_date": (date.today() + timedelta(days=14)).isoformat(),
            "remarks": "",
        }
        data.update(overrides)
        return data

    def test_create_bottleneck(self):
        response = self.client.post(LIST_URL, self._payload(), format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["type"], "RISK")
        self.assertEqual(response.data["project_id"], self.project.id)
        self.assertEqual(response.data["assigned_to"]["name"], "Site Engineer")

    def test_list_requires_auth(self):
        self.client.credentials()
        response = self.client.get(LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_filter_by_type_and_status(self):
        self.client.post(
            LIST_URL,
            self._payload(type="RISK", status="OPEN"),
            format="json",
        )
        self.client.post(
            LIST_URL,
            self._payload(type="ISSUE", status="CLOSED"),
            format="json",
        )
        response = self.client.get(
            LIST_URL,
            {"project_id": self.project.id, "type": "RISK", "status": "OPEN"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get("results", response.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["type"], "RISK")

    def test_update_item(self):
        create = self.client.post(LIST_URL, self._payload(), format="json")
        pk = create.data["id"]
        response = self.client.patch(
            f"{LIST_URL}{pk}/",
            {"status": "IN_PROGRESS", "remarks": "Mitigation started"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "IN_PROGRESS")
        self.assertEqual(response.data["remarks"], "Mitigation started")

    def test_delete_item(self):
        create = self.client.post(LIST_URL, self._payload(), format="json")
        pk = create.data["id"]
        response = self.client.delete(f"{LIST_URL}{pk}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Bottleneck.objects.filter(pk=pk).exists())

    def test_summary_api(self):
        self.client.post(LIST_URL, self._payload(type="ISSUE"), format="json")
        action_resp = self.client.post(
            LIST_URL,
            self._payload(type="ACTION", status="CLOSED"),
            format="json",
        )
        self.assertEqual(action_resp.status_code, status.HTTP_201_CREATED)
        Bottleneck.objects.filter(pk=action_resp.data["id"]).update(
            target_date=date.today() - timedelta(days=2)
        )
        response = self.client.get(
            SUMMARY_URL, {"project_id": self.project.id}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total_issues"], 1)
        self.assertEqual(response.data["total_actions"], 1)
        self.assertIn("overdue_items", response.data)

    def test_summary_requires_project_id(self):
        response = self.client.get(SUMMARY_URL)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_target_date_validation(self):
        response = self.client.post(
            LIST_URL,
            self._payload(target_date=(date.today() - timedelta(days=1)).isoformat()),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("target_date", str(response.data).lower())

    def test_mandatory_fields(self):
        response = self.client.post(
            LIST_URL,
            {"project_id": self.project.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
