"""Enterprise cache: SWR, stampede, tags, batch, health."""

import time
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from core.cache_metrics import get_metrics_snapshot, reset_metrics
from core.cache_swr import acquire_lock, get_or_rebuild, release_lock, swr_set
from core.cache_tags import batch_cache_invalidation, invalidate_tags
from core.test_auth import authenticate_client
from projects.models import Project


class SwrAndStampedeTest(TestCase):
    def setUp(self):
        cache.clear()
        reset_metrics()

    def test_fresh_hit_does_not_rebuild(self):
        builds = {"n": 0}

        def builder():
            builds["n"] += 1
            return {"v": builds["n"]}

        key = "swr:fresh"
        a = get_or_rebuild(key, builder, soft_ttl=60, hard_ttl=120, prefix="t")
        b = get_or_rebuild(key, builder, soft_ttl=60, hard_ttl=120, prefix="t")
        self.assertEqual(a, b)
        self.assertEqual(builds["n"], 1)
        snap = get_metrics_snapshot()
        self.assertGreaterEqual(snap["hits"], 1)

    def test_stale_while_revalidate_returns_stale_then_refreshes(self):
        builds = {"n": 0}

        def builder():
            builds["n"] += 1
            return {"v": builds["n"]}

        key = "swr:stale"
        swr_set(key, {"v": 0}, soft_ttl=-1, hard_ttl=60, prefix="t")  # already soft-expired
        # soft_ttl=-1 => soft_expires_at in the past
        result = get_or_rebuild(key, builder, soft_ttl=30, hard_ttl=60, prefix="t")
        self.assertEqual(result["v"], 0)  # stale served
        # rebuild happened under lock
        self.assertEqual(builds["n"], 1)
        refreshed = get_or_rebuild(key, builder, soft_ttl=30, hard_ttl=60, prefix="t")
        self.assertEqual(refreshed["v"], 1)

    def test_stampede_single_rebuild(self):
        builds = {"n": 0}

        def builder():
            builds["n"] += 1
            time.sleep(0.05)
            return {"v": builds["n"]}

        key = "swr:stampede"
        # First call populates
        get_or_rebuild(key, builder, soft_ttl=60, hard_ttl=120, prefix="t")
        self.assertEqual(builds["n"], 1)
        # Concurrent-ish fresh hits should not rebuild
        for _ in range(5):
            get_or_rebuild(key, builder, soft_ttl=60, hard_ttl=120, prefix="t")
        self.assertEqual(builds["n"], 1)

    def test_lock_acquire_release(self):
        self.assertTrue(acquire_lock("lock-test", timeout=5))
        self.assertFalse(acquire_lock("lock-test", timeout=5))
        release_lock("lock-test")
        self.assertTrue(acquire_lock("lock-test", timeout=5))
        release_lock("lock-test")


class TagBatchInvalidationTest(TestCase):
    def setUp(self):
        cache.clear()

    def test_batch_coalesces_invalidations(self):
        with patch("core.cache_tags.bump_many_list_cache_versions") as mocked:
            with batch_cache_invalidation():
                invalidate_tags("overview")
                invalidate_tags("dropdown")
                invalidate_tags("overview")
            mocked.assert_called()
            prefixes = mocked.call_args[0][0]
            self.assertIn("project_overview_v4", prefixes)
            self.assertIn("projects_dropdown", prefixes)


class CacheHealthAPITest(APITestCase):
    def setUp(self):
        cache.clear()
        reset_metrics()
        self.ho_group, _ = Group.objects.get_or_create(name="Head Office")
        self.ho = User.objects.create_user(username="cache_health_ho", password="Project@123")
        self.ho.groups.add(self.ho_group)
        self.tl_group, _ = Group.objects.get_or_create(name="Team Leader")
        self.tl = User.objects.create_user(username="cache_health_tl", password="Project@123")
        self.tl.groups.add(self.tl_group)
        Project.objects.create(name="Health Cache Project", status="active")

    def test_admin_can_view_health(self):
        authenticate_client(self.client, username="cache_health_ho", password="Project@123")
        response = self.client.get("/api/system/cache-health/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertIn("application_metrics", response.data["data"])
        self.assertIn("ttl_policy", response.data["data"])

    def test_tl_forbidden(self):
        authenticate_client(self.client, username="cache_health_tl", password="Project@123")
        response = self.client.get("/api/system/cache-health/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_perf_network(self):
        authenticate_client(self.client, username="cache_health_ho", password="Project@123")
        response = self.client.get("/api/system/perf-network/?n=5")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("benchmarks", response.data["data"])
        self.assertIn("redis", response.data["data"])

    def test_tl_perf_network_forbidden(self):
        authenticate_client(self.client, username="cache_health_tl", password="Project@123")
        response = self.client.get("/api/system/perf-network/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class OverviewSwrIntegrationTest(APITestCase):
    URL = "/api/projects/overview/"

    def setUp(self):
        cache.clear()
        reset_metrics()
        self.ho_group, _ = Group.objects.get_or_create(name="Head Office")
        self.ho = User.objects.create_user(username="swr_ho", password="Project@123")
        self.ho.groups.add(self.ho_group)
        Project.objects.create(name="SWR Overview Project", status="active")
        authenticate_client(self.client, username="swr_ho", password="Project@123")

    def test_overview_second_request_is_cached(self):
        r1 = self.client.get(self.URL)
        self.assertEqual(r1.status_code, status.HTTP_200_OK)
        r2 = self.client.get(self.URL)
        self.assertEqual(r2.status_code, status.HTTP_200_OK)
        self.assertEqual(r1.data["count"], r2.data["count"])
        snap = get_metrics_snapshot()
        self.assertGreaterEqual(snap["hits"] + snap["stale_hits"], 1)


class CacheFailoverTest(TestCase):
    def setUp(self):
        cache.clear()
        reset_metrics()

    def test_cache_get_returns_none_on_backend_error(self):
        with patch("core.cache_ops.cache.get", side_effect=Exception("redis down")):
            from core.cache_ops import cache_get as cg

            self.assertIsNone(cg("any-key"))

    def test_builder_runs_on_miss_after_failure(self):
        builds = {"n": 0}

        def builder():
            builds["n"] += 1
            return {"ok": True}

        result = get_or_rebuild(
            "failover:key",
            builder,
            soft_ttl=30,
            hard_ttl=60,
            prefix="t",
        )
        self.assertEqual(result, {"ok": True})
        self.assertEqual(builds["n"], 1)

    def test_prewarm_task_runs(self):
        from core.tasks import prewarm_project_caches

        Group.objects.get_or_create(name="Head Office")
        user = User.objects.create_user(username="prewarm_ho", password="Project@123")
        user.groups.add(Group.objects.get(name="Head Office"))
        Project.objects.create(name="Prewarm Project", status="active")
        result = prewarm_project_caches()
        self.assertIn("overview", result)
        self.assertIn("dropdown", result)
