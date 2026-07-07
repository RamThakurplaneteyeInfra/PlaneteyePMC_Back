"""
JWT authentication tests — /api/token/ and /api/accounts/me/
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

User = get_user_model()

TOKEN_URL = "/api/token/"
REFRESH_URL = "/api/token/refresh/"
LOGOUT_URL = "/api/auth/logout/"
ME_URL = "/api/accounts/me/"
AUTH_ME_URL = "/api/auth/me/"


class JWTAuthTestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="jwt_test_user",
            email="jwt@test.com",
            password="testpass123",
            first_name="JWT",
            last_name="Tester",
        )

    def _login(self):
        return self.client.post(
            TOKEN_URL,
            {"username": "jwt_test_user", "password": "testpass123"},
            format="json",
        )

    def test_login_success(self):
        response = self._login()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        self.assertEqual(response.data["user"]["username"], "jwt_test_user")

    def test_demo_role_user_login(self):
        """Frontend uses Project@123 for all role demo accounts (e.g. pmc_tl)."""
        from django.core.management import call_command

        call_command("create_demo_users", verbosity=0)
        response = self.client.post(
            TOKEN_URL,
            {"username": "pmc_tl", "password": "Project@123"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["user"]["username"], "pmc_tl")

    def test_login_invalid_credentials_message(self):
        response = self.client.post(
            TOKEN_URL,
            {"username": "jwt_test_user", "password": "wrong"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("Invalid username/password", str(response.data))

    def test_login_with_email_field(self):
        response = self.client.post(
            TOKEN_URL,
            {"email": "jwt@test.com", "password": "testpass123"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["user"]["username"], "jwt_test_user")

    def test_login_with_email_as_username_value(self):
        response = self.client.post(
            TOKEN_URL,
            {"username": "jwt@test.com", "password": "testpass123"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["user"]["email"], "jwt@test.com")

    def test_login_case_insensitive_username(self):
        response = self.client.post(
            TOKEN_URL,
            {"username": "JWT_TEST_USER", "password": "testpass123"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["user"]["username"], "jwt_test_user")

    def test_accounts_me_with_bearer(self):
        login = self._login()
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {login.data['access']}"
        )
        response = self.client.get(ME_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["username"], "jwt_test_user")

    def test_accounts_me_without_token(self):
        response = self.client.get(ME_URL)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_token_refresh(self):
        login = self._login()
        response = self.client.post(
            REFRESH_URL,
            {"refresh": login.data["refresh"]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)

    def test_logout_blacklists_refresh(self):
        login = self._login()
        refresh = login.data["refresh"]
        self.client.post(LOGOUT_URL, {"refresh": refresh}, format="json")
        response = self.client.post(
            REFRESH_URL, {"refresh": refresh}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_expired_token_rejected(self):
        token = AccessToken.for_user(self.user)
        token.set_exp(lifetime=timedelta(seconds=-1))
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(
            self.client.get(AUTH_ME_URL).status_code,
            status.HTTP_401_UNAUTHORIZED,
        )


class RefreshTokenModelTest(TestCase):
    def test_refresh_token_for_user(self):
        user = User.objects.create_user(username="t", password="pass12345")
        self.assertTrue(str(RefreshToken.for_user(user)))
