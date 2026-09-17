"""
Assign PMC Team Leaders to projects (Project.team_lead).

Creates pmc_tl14–pmc_tl23 if missing; refreshes pmc_tl1–pmc_tl13.
One Team Leader ↔ one project among the mapped set. Idempotent.

Run:
  python manage.py assign_pmc_team_leader_projects
  py -3.11 manage.py assign_pmc_team_leader_projects
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import UserProfile
from projects.models import Project

from projects.pmc_team_mappings import TL_PROJECT_MAPPINGS

TEAM_LEADER_GROUP = "Team Leader"
PMC_TEAM_LEADER_DESIGNATION = "PMC Team Leader"


def _password_for_username(username: str) -> str:
    suffix = username.removeprefix("pmc_tl")
    return f"tl@{suffix}"


def _resolve_project(name: str) -> Project | None:
    name = name.strip()
    project = Project.objects.filter(name=name).first()
    if project:
        return project
    return Project.objects.filter(name__iexact=name).first()


class Command(BaseCommand):
    help = (
        "Provision PMC Team Leader users and assign each to exactly one project "
        "via Project.team_lead. Safe to re-run."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        create_missing = True

        group, _ = Group.objects.get_or_create(name=TEAM_LEADER_GROUP)

        users_created = 0
        users_updated = 0
        projects_created = 0
        projects_assigned = 0
        failures: list[str] = []
        mapping_rows: list[tuple[str, str, str]] = []

        users_by_username: dict[str, User] = {}

        for username, _project_name in TL_PROJECT_MAPPINGS:
            password = _password_for_username(username)
            user, is_created = User.objects.get_or_create(
                username=username,
                defaults={"is_active": True},
            )
            if is_created:
                users_created += 1
            else:
                users_updated += 1

            user.is_active = True
            user.set_password(password)
            user.save()

            user.groups.clear()
            user.groups.add(group)

            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.designation = PMC_TEAM_LEADER_DESIGNATION
            profile.save(update_fields=["designation", "updated_at"])

            if not user.groups.filter(name=TEAM_LEADER_GROUP).exists():
                failures.append(
                    f"{username}: failed to assign {TEAM_LEADER_GROUP} group"
                )
                continue

            users_by_username[username] = user

        mapped_user_ids = [u.id for u in users_by_username.values()]
        if mapped_user_ids:
            Project.objects.filter(team_lead_id__in=mapped_user_ids).update(
                team_lead=None
            )

        for username, project_name in TL_PROJECT_MAPPINGS:
            user = users_by_username.get(username)
            if not user:
                mapping_rows.append((username, project_name, "FAILED (user)"))
                continue

            project = _resolve_project(project_name)
            if project is None:
                if create_missing:
                    project, proj_created = Project.objects.get_or_create(
                        name=project_name,
                        defaults={"status": "active"},
                    )
                    if proj_created:
                        projects_created += 1
                else:
                    msg = f"{username}: project not found — {project_name!r}"
                    failures.append(msg)
                    mapping_rows.append((username, project_name, "FAILED (project)"))
                    continue

            if project.team_lead_id and project.team_lead_id != user.id:
                project.team_lead = None
                project.save(update_fields=["team_lead", "updated_at"])

            project.team_lead = user
            project.save(update_fields=["team_lead", "updated_at"])
            projects_assigned += 1
            mapping_rows.append((username, project.name, "ASSIGNED"))

        self.stdout.write("")
        self.stdout.write("=" * 72)
        self.stdout.write(
            self.style.SUCCESS("PMC Team Leader <-> Project assignment complete")
        )
        self.stdout.write("=" * 72)
        self.stdout.write(f"Users created:      {users_created}")
        self.stdout.write(f"Users updated:      {users_updated}")
        self.stdout.write(f"Projects created:   {projects_created}")
        self.stdout.write(f"Projects assigned:  {projects_assigned}")
        self.stdout.write(f"Assignment failures: {len(failures)}")

        if failures:
            self.stdout.write("")
            self.stdout.write(self.style.ERROR("Failures:"))
            for item in failures:
                self.stdout.write(f"  - {item}")

        self.stdout.write("")
        self.stdout.write("Username <-> Project mapping:")
        self.stdout.write(f"{'Username':<12} {'Status':<18} Project")
        self.stdout.write("-" * 72)
        for username, project_name, status in mapping_rows:
            self.stdout.write(f"{username:<12} {status:<18} {project_name}")
        self.stdout.write("=" * 72)
