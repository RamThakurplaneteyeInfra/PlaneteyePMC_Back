"""Tests for Billing Site Engineer → Team Leader billing update notifications."""

from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.db import transaction
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Notification
from core.test_auth import authenticate_client
from contractors.models import Contractor
from projects.models import Project
from services.billing_update_notifications import (
    BillingAction,
    BillingModule,
    build_billing_update_message,
    notify_team_leader,
    schedule_billing_update_notification,
)


class BillingUpdateNotificationServiceTest(TestCase):
    def setUp(self):
        self.tl_group, _ = Group.objects.get_or_create(name="Team Leader")
        self.bse_group, _ = Group.objects.get_or_create(name="Billing Site Engineer")

        self.project = Project.objects.create(name="Thane Project", status="active")
        self.other_project = Project.objects.create(name="Other Project", status="active")

        self.tl = User.objects.create_user(
            "thane_tl",
            password="testpass123",
            first_name="Team",
            last_name="Leader",
        )
        self.other_tl = User.objects.create_user("other_tl", password="testpass123")
        self.bse = User.objects.create_user(
            "thane_bse",
            password="testpass123",
            first_name="Rahul",
            last_name="Patil",
        )
        self.se = User.objects.create_user("thane_se", password="testpass123")

        self.tl.groups.add(self.tl_group)
        self.other_tl.groups.add(self.tl_group)
        self.bse.groups.add(self.bse_group)
        self.se.groups.add(Group.objects.get_or_create(name="Site Engineer")[0])

        self.project.team_lead = self.tl
        self.project.billing_site_engineer = self.bse
        self.project.save()
        self.other_project.team_lead = self.other_tl
        self.other_project.save()

    def test_notify_team_leader_creates_notification(self):
        notification = notify_team_leader(
            self.project,
            self.bse,
            BillingModule.CONTRACT_VALUES,
            BillingAction.UPDATE,
        )
        self.assertIsNotNone(notification)
        self.assertEqual(notification.user_id, self.tl.id)
        self.assertEqual(notification.sender_id, self.bse.id)
        self.assertEqual(notification.project_id, self.project.id)
        self.assertEqual(notification.module_name, BillingModule.CONTRACT_VALUES)
        self.assertEqual(notification.action_type, BillingAction.UPDATE)
        self.assertEqual(notification.notification_type, "BILLING_UPDATE")
        self.assertEqual(notification.title, "Billing Data Updated")
        self.assertIn("Rahul Patil", notification.message)
        self.assertIn("Contract Values", notification.message)
        self.assertIn("Thane Project", notification.message)

    def test_non_bse_does_not_create_notification(self):
        notification = notify_team_leader(
            self.project,
            self.se,
            BillingModule.CONTRACT_VALUES,
            BillingAction.CREATE,
        )
        self.assertIsNone(notification)
        self.assertEqual(Notification.objects.count(), 0)

    def test_other_team_leader_does_not_receive_notification(self):
        notify_team_leader(
            self.project,
            self.bse,
            BillingModule.CONTRACT_VALUES,
            BillingAction.CREATE,
        )
        self.assertFalse(
            Notification.objects.filter(user=self.other_tl).exists()
        )

    def test_build_message_uses_action_verb(self):
        message = build_billing_update_message(
            "Rahul Patil",
            BillingModule.CONTRACT_VALUES,
            "Thane Project",
            BillingAction.CREATE,
        )
        self.assertIn("created", message)

    def test_schedule_deduplicates_within_transaction(self):
        with self.captureOnCommitCallbacks(execute=True):
            with transaction.atomic():
                schedule_billing_update_notification(
                    self.bse,
                    self.project,
                    BillingModule.CASH_FLOW,
                    BillingAction.CREATE,
                )
                schedule_billing_update_notification(
                    self.bse,
                    self.project,
                    BillingModule.CASH_FLOW,
                    BillingAction.CREATE,
                )
        self.assertEqual(Notification.objects.count(), 1)

    def test_failed_transaction_does_not_create_notification(self):
        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    schedule_billing_update_notification(
                        self.bse,
                        self.project,
                        BillingModule.INVOICING,
                        BillingAction.UPDATE,
                    )
                    raise RuntimeError("rollback")
            except RuntimeError:
                pass
        self.assertEqual(Notification.objects.count(), 0)


class BillingUpdateNotificationAPITest(APITestCase):
    CREATE_URL = "/api/contract-values/"
    ALERTS_URL = "/api/alerts/"

    def setUp(self):
        self.project = Project.objects.create(name="Thane Project", status="active")
        self.other_project = Project.objects.create(name="Pune Project", status="active")

        self.tl_group, _ = Group.objects.get_or_create(name="Team Leader")
        self.bse_group, _ = Group.objects.get_or_create(name="Billing Site Engineer")

        self.tl = User.objects.create_user("notify_tl", password="testpass123")
        self.other_tl = User.objects.create_user("notify_other_tl", password="testpass123")
        self.bse = User.objects.create_user(
            "notify_bse",
            password="testpass123",
            first_name="Rahul",
            last_name="Patil",
        )

        self.tl.groups.add(self.tl_group)
        self.other_tl.groups.add(self.tl_group)
        self.bse.groups.add(self.bse_group)

        self.project.team_lead = self.tl
        self.project.billing_site_engineer = self.bse
        self.project.save()
        self.other_project.team_lead = self.other_tl
        self.other_project.save()

        Contractor.objects.get_or_create(
            project=self.project,
            contractor_name="ABC Infra",
            defaults={"status": Contractor.Status.ACTIVE},
        )

    def _post_contract_value_as_bse(self, **overrides):
        authenticate_client(self.client, username="notify_bse", password="testpass123")
        payload = {
            "project_name": "Thane Project",
            "contract_type": "SCL",
            "original_contract_value": "10000000.00",
            "excess_value": "500000.00",
            "saving": "250000.00",
        }
        payload.update(overrides)
        return self.client.post(self.CREATE_URL, payload, format="json")

    def test_bse_create_notifies_team_leader(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self._post_contract_value_as_bse()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        notifications = Notification.objects.filter(user=self.tl)
        self.assertEqual(notifications.count(), 1)
        note = notifications.first()
        self.assertEqual(note.module_name, BillingModule.CONTRACT_VALUES)
        self.assertEqual(note.action_type, BillingAction.CREATE)
        self.assertEqual(note.project_id, self.project.id)
        self.assertIn("Rahul Patil", note.message)

    def test_bse_update_notifies_team_leader(self):
        with self.captureOnCommitCallbacks(execute=True):
            self._post_contract_value_as_bse()
            response = self._post_contract_value_as_bse(original_contract_value="11000000.00")
        self.assertIn(response.status_code, (status.HTTP_200_OK, status.HTTP_201_CREATED))

        update_notes = Notification.objects.filter(
            user=self.tl,
            action_type=BillingAction.UPDATE,
        )
        self.assertEqual(update_notes.count(), 1)

    def test_other_team_leader_not_notified(self):
        with self.captureOnCommitCallbacks(execute=True):
            self._post_contract_value_as_bse()
        self.assertFalse(Notification.objects.filter(user=self.other_tl).exists())

    def test_alerts_api_returns_notification_for_team_leader(self):
        with self.captureOnCommitCallbacks(execute=True):
            self._post_contract_value_as_bse()

        authenticate_client(self.client, username="notify_tl", password="testpass123")
        response = self.client.get(self.ALERTS_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(len(response.data["data"]), 1)

        alert = response.data["data"][0]
        self.assertEqual(alert["title"], "Billing Data Updated")
        self.assertEqual(alert["module_name"], BillingModule.CONTRACT_VALUES)
        self.assertEqual(alert["project_name"], "Thane Project")
        self.assertEqual(alert["action_type"], BillingAction.CREATE)
        self.assertEqual(alert["notification_type"], "BILLING_UPDATE")
        self.assertEqual(alert["sender"], "Rahul Patil")
        self.assertFalse(alert["is_read"])

    def test_mark_alert_read(self):
        with self.captureOnCommitCallbacks(execute=True):
            self._post_contract_value_as_bse()
        note = Notification.objects.get(user=self.tl)

        authenticate_client(self.client, username="notify_tl", password="testpass123")
        response = self.client.patch(
            f"{self.ALERTS_URL}{note.id}/",
            {"is_read": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["data"]["is_read"])

        note.refresh_from_db()
        self.assertTrue(note.is_read)

    def test_failed_validation_does_not_create_notification(self):
        authenticate_client(self.client, username="notify_bse", password="testpass123")
        response = self.client.post(
            self.CREATE_URL,
            {
                "project_name": "Thane Project",
                "contract_type": "SCL",
                "original_contract_value": "-1",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Notification.objects.count(), 0)

    def test_single_request_creates_single_notification_on_upsert(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self._post_contract_value_as_bse()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Notification.objects.filter(user=self.tl).count(), 1)
