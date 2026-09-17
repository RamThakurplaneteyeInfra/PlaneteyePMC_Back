"""Tests for RBAC-aware list cache keys."""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import RequestFactory, TestCase

from accounts.models import UserProfile
from core.cache_keys import (
    build_rbac_list_cache_key,
    invalidate_list_cache,
    rbac_dataset_scope,
)
from projects.models import Project

User = get_user_model()


class RbacCacheKeyTests(TestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()
        self.project_a = Project.objects.create(name="Cache Project A", status="active")
        self.project_b = Project.objects.create(name="Cache Project B", status="active")

        self.admin_group, _ = Group.objects.get_or_create(name="PMC Head")
        self.tl_group, _ = Group.objects.get_or_create(name="Team Leader")

        self.admin = User.objects.create_user(username="cache_admin", password="x")
        self.admin.groups.add(self.admin_group)
        UserProfile.objects.get_or_create(user=self.admin)

        self.tl1 = User.objects.create_user(username="cache_tl1", password="x")
        self.tl1.groups.add(self.tl_group)
        UserProfile.objects.get_or_create(user=self.tl1)
        self.project_a.team_lead = self.tl1
        self.project_a.save(update_fields=["team_lead"])

        self.tl2 = User.objects.create_user(username="cache_tl2", password="x")
        self.tl2.groups.add(self.tl_group)
        UserProfile.objects.get_or_create(user=self.tl2)
        self.project_b.team_lead = self.tl2
        self.project_b.save(update_fields=["team_lead"])

        self.tl1_same = User.objects.create_user(username="cache_tl1b", password="x")
        self.tl1_same.groups.add(self.tl_group)
        UserProfile.objects.get_or_create(user=self.tl1_same)
        self.project_a.site_engineers.add(self.tl1_same)

    def test_admins_share_scope(self):
        admin2 = User.objects.create_user(username="cache_admin2", password="x")
        admin2.groups.add(self.admin_group)
        self.assertEqual(rbac_dataset_scope(self.admin), "admin")
        self.assertEqual(rbac_dataset_scope(admin2), "admin")

    def test_different_projects_different_scope(self):
        self.assertNotEqual(rbac_dataset_scope(self.tl1), rbac_dataset_scope(self.tl2))

    def test_same_project_assignment_shares_scope(self):
        self.assertEqual(rbac_dataset_scope(self.tl1), rbac_dataset_scope(self.tl1_same))

    def test_list_keys_differ_across_scopes(self):
        req1 = self.factory.get("/api/invoicing/")
        req1.user = self.tl1
        req2 = self.factory.get("/api/invoicing/")
        req2.user = self.tl2
        key1 = build_rbac_list_cache_key("invoicing_list", req1)
        key2 = build_rbac_list_cache_key("invoicing_list", req2)
        self.assertNotEqual(key1, key2)

    def test_same_scope_same_filters_share_key(self):
        req1 = self.factory.get("/api/invoicing/")
        req1.user = self.tl1
        req2 = self.factory.get("/api/invoicing/")
        req2.user = self.tl1_same
        self.assertEqual(
            build_rbac_list_cache_key("invoicing_list", req1),
            build_rbac_list_cache_key("invoicing_list", req2),
        )

    def test_invalidate_bumps_version(self):
        req = self.factory.get("/api/invoicing/")
        req.user = self.tl1
        before = build_rbac_list_cache_key("invoicing_list", req)
        invalidate_list_cache("invoicing_list")
        after = build_rbac_list_cache_key("invoicing_list", req)
        self.assertNotEqual(before, after)

    def test_invalidate_skips_scan_by_default(self):
        from unittest.mock import MagicMock

        cache.delete_pattern = MagicMock()
        invalidate_list_cache("dpr_list")
        cache.delete_pattern.assert_not_called()


class RedisHostClassificationTests(TestCase):
    def test_classifies_proxy_and_internal(self):
        from core.perf_network import classify_neon_host, classify_redis_host

        self.assertEqual(classify_redis_host("sakura.proxy.rlwy.net"), "PUBLIC / EXTERNAL")
        self.assertEqual(classify_redis_host("redis.railway.internal"), "PRIVATE / INTERNAL")
        self.assertEqual(classify_redis_host("127.0.0.1"), "LOCAL")
        neon = classify_neon_host("ep-x-pooler.c-2.ap-southeast-1.aws.neon.tech")
        self.assertEqual(neon["endpoint_type"], "pooler")
        self.assertEqual(neon["region"], "ap-southeast-1")
