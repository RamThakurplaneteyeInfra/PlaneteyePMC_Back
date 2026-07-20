"""RBAC project resolution prefers the caller's assigned project on name casing duplicates."""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserProfile
from accounts.rbac import RBACDomain, resolve_project, user_can_write_domain
from projects.models import Project

User = get_user_model()


class ResolveProjectCaseDuplicateTests(APITestCase):
    def setUp(self):
        # Two rows that differ only by casing — mirrors production KHB/Khb issue.
        self.assigned = Project.objects.create(
            name="KHB Multiplex, Kengeri (A-3462)",
            status="active",
        )
        self.orphan = Project.objects.create(
            name="Khb Multiplex, Kengeri (A-3462)",
            status="active",
        )

        self.hse = User.objects.create_user(username="pmc_hse_case", password="testpass123")
        group, _ = Group.objects.get_or_create(name="HSE Site Engineer")
        self.hse.groups.add(group)
        UserProfile.objects.get_or_create(user=self.hse)
        self.assigned.hse_site_engineer = self.hse
        self.assigned.save(update_fields=["hse_site_engineer", "updated_at"])

    def test_resolve_prefers_assigned_project(self):
        resolved = resolve_project("Khb Multiplex, Kengeri (A-3462)", user=self.hse)
        self.assertEqual(resolved.pk, self.assigned.pk)
        self.assertTrue(user_can_write_domain(self.hse, resolved, RBACDomain.QAQC))

    def test_health_safety_post_with_mismatched_casing(self):
        login = self.client.post(
            "/api/token/",
            {"username": "pmc_hse_case", "password": "testpass123"},
            format="json",
        )
        self.assertEqual(login.status_code, status.HTTP_200_OK)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

        response = self.client.post(
            "/api/health-safety/",
            {
                "project_name": "Khb Multiplex, Kengeri (A-3462)",
                "month": 7,
                "year": 2026,
                "average_daily_manpower": 11,
                "working_days": 26,
                "near_miss": 2,
                "loss_of_manhours": 11,
            },
            format="json",
        )
        self.assertIn(
            response.status_code,
            (status.HTTP_200_OK, status.HTTP_201_CREATED),
            response.data,
        )
        self.assertTrue(response.data.get("success"))
