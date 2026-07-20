"""RBAC filter and pending-query regression helpers."""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase

from accounts.models import UserProfile
from accounts.rbac import filter_queryset_by_project_access
from contractors.models import Contractor
from planned_earned_value.models import PlannedEarnedValue
from projects.models import Project

User = get_user_model()


class RbacFilterOptimizationTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name="RBAC Opt Project", status="active")
        self.other = Project.objects.create(name="Other Project", status="active")
        group, _ = Group.objects.get_or_create(name="Team Leader")
        self.user = User.objects.create_user(username="rbac_opt_tl", password="x")
        self.user.groups.add(group)
        UserProfile.objects.get_or_create(user=self.user)
        self.project.team_lead = self.user
        self.project.save(update_fields=["team_lead"])

        PlannedEarnedValue.objects.create(
            project=self.project,
            project_name=self.project.name,
            planned_type=PlannedEarnedValue.TYPE_SCL,
            month=7,
            year=2026,
            planned_value=100,
            actual_value=100,
            collection=100,
        )
        PlannedEarnedValue.objects.create(
            project=self.other,
            project_name=self.other.name,
            planned_type=PlannedEarnedValue.TYPE_SCL,
            month=7,
            year=2026,
            planned_value=50,
            actual_value=50,
            collection=50,
        )

    def test_filter_is_case_insensitive_and_scoped(self):
        qs = PlannedEarnedValue.objects.all()
        filtered = filter_queryset_by_project_access(qs, self.user, "project_name")
        names = set(filtered.values_list("project_name", flat=True))
        self.assertEqual(names, {self.project.name})

        # Mixed-case stored name still matches assigned project.
        PlannedEarnedValue.objects.filter(project=self.project).update(
            project_name=self.project.name.upper()
        )
        filtered2 = filter_queryset_by_project_access(
            PlannedEarnedValue.objects.all(), self.user, "project_name"
        )
        self.assertEqual(filtered2.count(), 1)
