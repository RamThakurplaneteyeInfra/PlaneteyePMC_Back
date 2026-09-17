"""Tests for PMC API rate limiting (DRF throttling)."""

from copy import deepcopy
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser, Group, User
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIRequestFactory, APITestCase

from contractors.models import Contractor
from core.test_auth import authenticate_client
from core.throttling import (
    CreateRateThrottle,
    DeleteRateThrottle,
    ExportRateThrottle,
    FastUserRateThrottle,
    LoginRateThrottle,
    NotificationRateThrottle,
    RefreshRateThrottle,
    SearchRateThrottle,
    UpdateRateThrottle,
    UploadRateThrottle,
)
from projects.models import Project

_TEST_THROTTLE_RATES = {
    "anon": "3/min",
    "user": "5/min",
    "login": "2/min",
    "refresh": "2/min",
    "create": "2/min",
    "update": "2/min",
    "delete": "2/min",
    "export": "2/min",
    "upload": "2/min",
    "alerts": "2/min",
    "search": "2/min",
}


def _test_rest_framework_settings():
    from django.conf import settings

    rf = deepcopy(settings.REST_FRAMEWORK)
    rf["DEFAULT_THROTTLE_RATES"] = _TEST_THROTTLE_RATES
    return rf


def _reload_drf_api_settings():
    from rest_framework.settings import api_settings

    api_settings.reload()


class ThrottleTestContext:
    """Context manager applying low throttle rates for tests."""

    def __enter__(self):
        self._override = override_settings(REST_FRAMEWORK=_test_rest_framework_settings())
        self._override.enable()
        _reload_drf_api_settings()
        cache.clear()
        return self

    def __exit__(self, *args):
        cache.clear()
        self._override.disable()
        _reload_drf_api_settings()


class ThrottleClassUnitTest(TestCase):
    def setUp(self):
        cache.clear()
        self.factory = APIRequestFactory()
        self.view = type("DummyView", (), {"apply_method_scoped_throttle": False})()

    def _request(self, method, path, data=None, **kwargs):
        factory_method = getattr(self.factory, method.lower())
        if data is not None:
            request = factory_method(path, data, **kwargs)
        else:
            request = factory_method(path, **kwargs)
        request.user = AnonymousUser()
        return request

    def _assert_throttle_blocks_on_third_request(self, throttle, request):
        with ThrottleTestContext():
            self.assertTrue(throttle.allow_request(request, self.view))
            self.assertTrue(throttle.allow_request(request, self.view))
            self.assertFalse(throttle.allow_request(request, self.view))

    def test_login_throttle_blocks_after_limit(self):
        throttle = LoginRateThrottle()
        request = self._request("post", "/api/token/")
        self._assert_throttle_blocks_on_third_request(throttle, request)

    def test_refresh_throttle_blocks_after_limit(self):
        throttle = RefreshRateThrottle()
        request = self._request("post", "/api/token/refresh/")
        self._assert_throttle_blocks_on_third_request(throttle, request)

    def test_create_throttle_on_financial_post(self):
        throttle = CreateRateThrottle()
        request = self._request("post", "/api/contract-values/")
        self._assert_throttle_blocks_on_third_request(throttle, request)

    def test_update_throttle_on_financial_patch(self):
        throttle = UpdateRateThrottle()
        request = self._request("patch", "/api/contract-values/1/")
        self._assert_throttle_blocks_on_third_request(throttle, request)

    def test_delete_throttle_on_financial_delete(self):
        throttle = DeleteRateThrottle()
        request = self._request("delete", "/api/contract-values/1/")
        self._assert_throttle_blocks_on_third_request(throttle, request)

    def test_export_throttle_with_query_param(self):
        throttle = ExportRateThrottle()
        request = self._request("get", "/api/project-dates/", data={"export": "csv"})
        self._assert_throttle_blocks_on_third_request(throttle, request)

    def test_upload_throttle_on_site_images(self):
        throttle = UploadRateThrottle()
        request = self._request("post", "/api/site-images/")
        self._assert_throttle_blocks_on_third_request(throttle, request)

    def test_alerts_throttle(self):
        throttle = NotificationRateThrottle()
        request = self._request("get", "/api/alerts/")
        self._assert_throttle_blocks_on_third_request(throttle, request)

    def test_search_throttle_with_search_param(self):
        throttle = SearchRateThrottle()
        request = self._request("get", "/api/contract-values/", data={"search": "test"})
        self._assert_throttle_blocks_on_third_request(throttle, request)

    def test_cache_backend_used(self):
        throttle = LoginRateThrottle()
        self.assertEqual(throttle.cache, cache)

    def test_fast_user_throttle_falls_back_to_cache_backend(self):
        from unittest.mock import patch

        throttle = FastUserRateThrottle()
        throttle.rate = "2/min"
        throttle.num_requests, throttle.duration = throttle.parse_rate("2/min")
        request = self._request("get", "/api/dpr/")
        request.user = User.objects.create_user("fast_throttle_user", password="x")
        with ThrottleTestContext():
            with patch.object(throttle, "_allow_via_redis", return_value=None):
                self.assertTrue(throttle.allow_request(request, self.view))
                self.assertTrue(throttle.allow_request(request, self.view))
                self.assertFalse(throttle.allow_request(request, self.view))

    @patch("core.throttling.logger.warning")
    def test_throttled_request_is_logged(self, mock_log):
        throttle = LoginRateThrottle()
        request = self._request("post", "/api/token/")
        with ThrottleTestContext():
            for _ in range(3):
                throttle.allow_request(request, self.view)
        self.assertTrue(mock_log.called)


class LoginIntegrationTest(APITestCase):
    TOKEN_URL = "/api/token/"

    def setUp(self):
        User.objects.create_user("throttle_user", password="testpass123")

    def test_login_http_429_response_format(self):
        payload = {"username": "throttle_user", "password": "testpass123"}
        with ThrottleTestContext():
            for _ in range(2):
                self.client.post(self.TOKEN_URL, payload, format="json")
            response = self.client.post(self.TOKEN_URL, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertFalse(response.data["success"])
        self.assertIn("Rate limit exceeded", response.data["message"])
        self.assertIsInstance(response.data["errors"], list)
        self.assertTrue(response.data["errors"])
        self.assertIn("message", response.data["errors"][0])
        self.assertIn("Retry-After", response)


class RefreshIntegrationTest(APITestCase):
    def test_refresh_http_429(self):
        with ThrottleTestContext():
            for _ in range(2):
                self.client.post("/api/token/refresh/", {"refresh": "invalid"}, format="json")
            response = self.client.post(
                "/api/token/refresh/", {"refresh": "invalid"}, format="json"
            )

        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)


class FinancialModuleIntegrationTest(APITestCase):
    CREATE_URL = "/api/contract-values/"

    def setUp(self):
        self.project = Project.objects.create(name="Throttle Project", status="active")
        bse_group, _ = Group.objects.get_or_create(name="Billing Site Engineer")
        tl_group, _ = Group.objects.get_or_create(name="Team Leader")
        self.bse = User.objects.create_user("throttle_bse", password="testpass123")
        self.bse.groups.add(bse_group)
        self.tl = User.objects.create_user("throttle_tl", password="testpass123")
        self.tl.groups.add(tl_group)
        self.project.billing_site_engineer = self.bse
        self.project.team_lead = self.tl
        self.project.save()

    def test_authenticated_post_http_429(self):
        with ThrottleTestContext():
            authenticate_client(self.client, username="throttle_bse", password="testpass123")
            payload = {
                "project_name": "Throttle Project",
                "contract_type": "SCL",
                "original_contract_value": "1000.00",
                "excess_value": "0.00",
                "saving": "0.00",
            }
            for _ in range(2):
                self.client.post(self.CREATE_URL, payload, format="json")
            response = self.client.post(self.CREATE_URL, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)


class AlertsIntegrationTest(APITestCase):
    def test_alerts_http_429(self):
        User.objects.create_user("alerts_tl", password="testpass123")
        with ThrottleTestContext():
            authenticate_client(self.client, username="alerts_tl", password="testpass123")
            for _ in range(2):
                self.client.get("/api/alerts/")
            response = self.client.get("/api/alerts/")

        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
