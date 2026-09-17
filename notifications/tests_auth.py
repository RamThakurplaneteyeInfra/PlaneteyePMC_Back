"""Notification test/debug endpoints must not be anonymous."""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserProfile

User = get_user_model()


class NotificationTestEndpointAuthTest(APITestCase):
    def test_send_test_requires_auth(self):
        response = self.client.get("/api/notifications/send-test/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        response_legacy = self.client.get("/notifications/send-test/")
        self.assertEqual(response_legacy.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_send_test_email_requires_auth(self):
        response = self.client.post(
            "/api/notifications/send-test-email/",
            data={"email": "a@b.com", "type": "test"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_test_sync_email_requires_auth(self):
        response = self.client.post("/api/notifications/test-sync-email/", {}, format="json")
        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )

    def test_non_admin_authenticated_forbidden(self):
        user = User.objects.create_user(username="notif_se", password="testpass123")
        group, _ = Group.objects.get_or_create(name="Site Engineer")
        user.groups.add(group)
        UserProfile.objects.get_or_create(user=user)

        login = self.client.post(
            "/api/token/",
            {"username": "notif_se", "password": "testpass123"},
            format="json",
        )
        self.assertEqual(login.status_code, status.HTTP_200_OK)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {login.data['access']}"
        )

        response = self.client.get("/api/notifications/send-test/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_access_send_test(self):
        admin = User.objects.create_user(
            username="notif_admin",
            password="testpass123",
            is_staff=True,
        )
        UserProfile.objects.get_or_create(user=admin)
        login = self.client.post(
            "/api/token/",
            {"username": "notif_admin", "password": "testpass123"},
            format="json",
        )
        self.assertEqual(login.status_code, status.HTTP_200_OK)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {login.data['access']}"
        )

        response = self.client.get("/api/notifications/send-test/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json().get("status"), "Notification sent")
