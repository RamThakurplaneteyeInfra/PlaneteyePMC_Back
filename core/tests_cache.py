"""Tests for Redis-backed cache helpers and dropdown caching."""

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from core.cache_keys import build_rbac_list_cache_key, invalidate_list_cache
from core.cache_ops import cache_get, cache_set
from core.test_auth import authenticate_client
from projects.models import Project


class CacheOpsTest(TestCase):
    def setUp(self):
        cache.clear()

    def test_cache_set_get_roundtrip(self):
        self.assertTrue(cache_set("pmc:test:key", {"ok": True}, 60, prefix="pmc_test"))
        self.assertEqual(cache_get("pmc:test:key", prefix="pmc_test"), {"ok": True})

    def test_cache_miss_returns_none(self):
        self.assertIsNone(cache_get("pmc:missing:key", prefix="pmc_test"))

    def test_invalidate_bumps_version(self):
        request = type("R", (), {"user": None, "META": {}, "query_params": {}})()
        key1 = build_rbac_list_cache_key("unit_prefix", request, use_query_string=False)
        cache_set(key1, {"v": 1}, 60)
        invalidate_list_cache("unit_prefix")
        key2 = build_rbac_list_cache_key("unit_prefix", request, use_query_string=False)
        self.assertNotEqual(key1, key2)
        self.assertIsNone(cache_get(key2))


class ProjectsDropdownCacheAPITest(APITestCase):
    URL = "/api/projects/dropdown/"

    def setUp(self):
        cache.clear()
        self.ho_group, _ = Group.objects.get_or_create(name="Head Office")
        self.tl_group, _ = Group.objects.get_or_create(name="Team Leader")
        self.ho = User.objects.create_user(username="cache_ho", password="Project@123")
        self.ho.groups.add(self.ho_group)
        self.tl = User.objects.create_user(username="cache_tl", password="Project@123")
        self.tl.groups.add(self.tl_group)
        self.p_active = Project.objects.create(name="Cache Active Project", status="active")
        self.p_assigned = Project.objects.create(
            name="Cache TL Project", status="active", team_lead=self.tl
        )
        authenticate_client(self.client, username="cache_ho", password="Project@123")

    def test_dropdown_cache_hit(self):
        r1 = self.client.get(self.URL, {"status": "active"})
        self.assertEqual(r1.status_code, status.HTTP_200_OK)
        r2 = self.client.get(self.URL, {"status": "active"})
        self.assertEqual(r2.status_code, status.HTTP_200_OK)
        self.assertEqual(r1.data["count"], r2.data["count"])
        self.assertEqual(r1.data["data"], r2.data["data"])

    def test_dropdown_rbac_isolation(self):
        ho_resp = self.client.get(self.URL, {"status": "active"})
        ho_names = {row["name"] for row in ho_resp.data["data"]}
        self.assertIn("Cache Active Project", ho_names)

        authenticate_client(self.client, username="cache_tl", password="Project@123")
        tl_resp = self.client.get(self.URL, {"status": "active"})
        tl_names = {row["name"] for row in tl_resp.data["data"]}
        self.assertEqual(tl_names, {"Cache TL Project"})
        self.assertNotIn("Cache Active Project", tl_names)

    def test_dropdown_invalidates_on_project_create(self):
        first = self.client.get(self.URL, {"status": "active"})
        self.assertNotIn(
            "Cache New Project",
            {row["name"] for row in first.data["data"]},
        )
        Project.objects.create(name="Cache New Project", status="active")
        second = self.client.get(self.URL, {"status": "active"})
        self.assertIn(
            "Cache New Project",
            {row["name"] for row in second.data["data"]},
        )


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "cache-fallback-test",
        }
    }
)
class CacheFallbackTest(TestCase):
    def test_locmem_still_works_when_redis_unavailable(self):
        cache.clear()
        cache_set("fallback:key", "value", 30)
        self.assertEqual(cache_get("fallback:key"), "value")
