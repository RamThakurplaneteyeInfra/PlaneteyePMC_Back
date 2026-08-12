"""Tests for PO-31 Reminders module."""

from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Notification
from core.test_auth import authenticate_client
from projects.models import Project
from reminders.models import Reminder
from reminders.services import dispatch_due_reminders


class ReminderAPITest(APITestCase):
    URL = "/api/reminders/"

    def setUp(self):
        cache.clear()
        self.ho_group, _ = Group.objects.get_or_create(name="Head Office")
        self.tl_group, _ = Group.objects.get_or_create(name="Team Leader")
        self.se_group, _ = Group.objects.get_or_create(name="Site Engineer")

        self.ho = User.objects.create_user(username="rem_ho", password="Project@123")
        self.ho.groups.add(self.ho_group)
        self.tl = User.objects.create_user(
            username="rem_tl", password="Project@123", first_name="Rem", last_name="Lead"
        )
        self.tl.groups.add(self.tl_group)
        self.se = User.objects.create_user(username="rem_se", password="Project@123")
        self.se.groups.add(self.se_group)
        self.outsider = User.objects.create_user(
            username="rem_out", password="Project@123"
        )
        self.outsider.groups.add(self.tl_group)

        self.project = Project.objects.create(
            name="Reminder Project Alpha",
            status="active",
            team_lead=self.tl,
        )
        self.project.site_engineers.add(self.se)
        self.other = Project.objects.create(
            name="Reminder Other Project",
            status="active",
            team_lead=self.outsider,
        )

    def _auth(self, username="rem_ho"):
        authenticate_client(self.client, username=username, password="Project@123")

    def _payload(self, **overrides):
        data = {
            "project_id": self.project.id,
            "title": "Submit weekly DPR",
            "description": "Ensure site DPR is uploaded",
            "due_at": (timezone.now() + timedelta(hours=2)).isoformat(),
            "assigned_to_id": self.tl.id,
        }
        data.update(overrides)
        return data

    def test_create_and_list(self):
        self._auth()
        response = self.client.post(self.URL, self._payload(), format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["data"]["title"], "Submit weekly DPR")
        self.assertEqual(response.data["data"]["status"], "pending")
        self.assertEqual(response.data["data"]["assigned_to"]["username"], "rem_tl")

        listed = self.client.get(self.URL)
        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        # DRF pagination envelope
        self.assertIn("results", listed.data)
        self.assertGreaterEqual(listed.data["count"], 1)

    def test_rbac_tl_sees_assigned_project_only(self):
        self._auth("rem_ho")
        self.client.post(self.URL, self._payload(), format="json")
        self.client.post(
            self.URL,
            self._payload(
                project_id=self.other.id,
                assigned_to_id=self.outsider.id,
                title="Other reminder",
            ),
            format="json",
        )

        self._auth("rem_tl")
        listed = self.client.get(self.URL)
        titles = [r["title"] for r in listed.data["results"]]
        self.assertIn("Submit weekly DPR", titles)
        self.assertNotIn("Other reminder", titles)

    def test_assignee_must_have_project_access(self):
        self._auth()
        response = self.client.post(
            self.URL,
            self._payload(assigned_to_id=self.outsider.id),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_filters_by_project_and_scope(self):
        self._auth()
        overdue = Reminder.objects.create(
            project=self.project,
            title="Overdue item",
            due_at=timezone.now() - timedelta(days=1),
            assigned_to=self.tl,
            created_by=self.ho,
        )
        upcoming = Reminder.objects.create(
            project=self.project,
            title="Upcoming item",
            due_at=timezone.now() + timedelta(days=2),
            assigned_to=self.tl,
            created_by=self.ho,
        )
        today = Reminder.objects.create(
            project=self.project,
            title="Today item",
            due_at=timezone.now() + timedelta(minutes=30),
            assigned_to=self.tl,
            created_by=self.ho,
        )

        overdue_resp = self.client.get(self.URL, {"scope": "overdue"})
        overdue_ids = {r["id"] for r in overdue_resp.data["results"]}
        self.assertIn(overdue.id, overdue_ids)
        self.assertNotIn(upcoming.id, overdue_ids)

        upcoming_resp = self.client.get(self.URL, {"scope": "upcoming"})
        upcoming_ids = {r["id"] for r in upcoming_resp.data["results"]}
        self.assertIn(upcoming.id, upcoming_ids)
        self.assertIn(today.id, upcoming_ids)
        self.assertNotIn(overdue.id, upcoming_ids)

        by_project = self.client.get(self.URL, {"project_id": self.project.id})
        self.assertTrue(
            all(r["project_id"] == self.project.id for r in by_project.data["results"])
        )

    def test_complete_dismiss_snooze(self):
        self._auth()
        created = self.client.post(self.URL, self._payload(), format="json")
        rid = created.data["data"]["id"]

        snooze = self.client.post(
            f"{self.URL}{rid}/snooze/", {"minutes": 60}, format="json"
        )
        self.assertEqual(snooze.status_code, status.HTTP_200_OK, snooze.data)
        self.assertEqual(snooze.data["data"]["status"], "pending")
        self.assertIsNotNone(snooze.data["data"]["snoozed_until"])

        complete = self.client.post(f"{self.URL}{rid}/complete/", {}, format="json")
        self.assertEqual(complete.status_code, status.HTTP_200_OK)
        self.assertEqual(complete.data["data"]["status"], "completed")

        created2 = self.client.post(
            self.URL, self._payload(title="Dismiss me"), format="json"
        )
        rid2 = created2.data["data"]["id"]
        dismiss = self.client.post(f"{self.URL}{rid2}/dismiss/", {}, format="json")
        self.assertEqual(dismiss.status_code, status.HTTP_200_OK)
        self.assertEqual(dismiss.data["data"]["status"], "dismissed")

    def test_patch_update(self):
        self._auth()
        created = self.client.post(self.URL, self._payload(), format="json")
        rid = created.data["data"]["id"]
        patched = self.client.patch(
            f"{self.URL}{rid}/",
            {"title": "Updated title", "description": "New notes"},
            format="json",
        )
        self.assertEqual(patched.status_code, status.HTTP_200_OK)
        self.assertEqual(patched.data["data"]["title"], "Updated title")

    def test_dispatch_due_creates_alert(self):
        reminder = Reminder.objects.create(
            project=self.project,
            title="Due now",
            description="Please act",
            due_at=timezone.now() - timedelta(minutes=1),
            assigned_to=self.tl,
            created_by=self.ho,
        )
        summary = dispatch_due_reminders()
        self.assertEqual(summary["sent"], 1)
        reminder.refresh_from_db()
        self.assertIsNotNone(reminder.notified_at)
        self.assertTrue(
            Notification.objects.filter(
                user=self.tl,
                notification_type=Notification.NOTIFICATION_TYPE_REMINDER_DUE,
                project=self.project,
            ).exists()
        )
        # Idempotent — second dispatch should skip
        summary2 = dispatch_due_reminders()
        self.assertEqual(summary2["sent"], 0)

    def test_inactive_assignee_clear_error(self):
        self.tl.is_active = False
        self.tl.save(update_fields=["is_active"])
        self._auth()
        response = self.client.post(
            self.URL, self._payload(assigned_to_id=self.tl.id), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        # Friendly field error (inactive, not generic "does not exist")
        err = str(response.data)
        self.assertIn("inactive", err.lower())
        self.assertIn(str(self.tl.id), err)

    def test_assignees_endpoint_returns_project_members(self):
        self._auth()
        response = self.client.get(
            f"{self.URL}assignees/", {"project_id": self.project.id}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        ids = {row["id"] for row in response.data["data"]}
        self.assertIn(self.tl.id, ids)
        self.assertIn(self.se.id, ids)
        self.assertNotIn(self.outsider.id, ids)
