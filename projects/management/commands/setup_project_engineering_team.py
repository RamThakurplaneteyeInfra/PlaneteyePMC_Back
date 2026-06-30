"""
Provision Site Engineer, Billing Site Engineer, and QA/QC Site Engineer users
and assign one of each to every PMC project (pmc_tl1–pmc_tl23 mapping).

Does NOT modify Team Leader assignments.

Run:
  py -3.11 manage.py setup_project_engineering_team
"""

from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import UserProfile
from projects.models import Project
from projects.pmc_team_mappings import TL_PROJECT_MAPPINGS

ENGINEER_ROLES = [
    {
        "username_prefix": "pmc_se",
        "password_prefix": "Pmc@SE",
        "group": "Site Engineer",
        "profile_type": "site_engineer",
        "designation": "Site Engineer",
        "project_field": "site_engineer",
        "sync_m2m": True,
    },
    {
        "username_prefix": "pmc_bse",
        "password_prefix": "Pmc@BSE",
        "group": "Billing Site Engineer",
        "profile_type": "billing_site_engineer",
        "designation": "Billing Site Engineer",
        "project_field": "billing_site_engineer",
        "sync_m2m": False,
    },
    {
        "username_prefix": "pmc_qaqc",
        "password_prefix": "Pmc@QA",
        "group": "QAQC Site Engineer",
        "profile_type": "qaqc_site_engineer",
        "designation": "QA/QC Site Engineer",
        "project_field": "qaqc_site_engineer",
        "sync_m2m": False,
    },
]


def _resolve_project(name: str) -> Project | None:
    name = name.strip()
    project = Project.objects.filter(name=name).first()
    if project:
        return project
    return Project.objects.filter(name__iexact=name).first()


class Command(BaseCommand):
    help = (
        "Create pmc_se1–23, pmc_bse1–23, pmc_qaqc1–23; assign groups, profiles, "
        "and map each engineer type to the same project as pmc_tlX. Idempotent."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()

        users_created = 0
        users_updated = 0
        role_assignments = 0
        projects_mapped = 0
        projects_created = 0
        failures: list[str] = []
        mapping_table: list[tuple[int, str, str, str, str, str, str, str]] = []

        groups: dict[str, Group] = {}
        for spec in ENGINEER_ROLES:
            group, _ = Group.objects.get_or_create(name=spec["group"])
            groups[spec["group"]] = group

        users_cache: dict[str, User] = {}

        for index, (_tl_username, project_name) in enumerate(TL_PROJECT_MAPPINGS, start=1):
            project = _resolve_project(project_name)
            if project is None:
                project, _proj_created = Project.objects.get_or_create(
                    name=project_name,
                    defaults={"status": "active"},
                )
                if _proj_created:
                    projects_created += 1

            tl_user = User.objects.filter(username=_tl_username).first()
            tl_label = _tl_username if tl_user else f"{_tl_username} (missing)"

            se_name = "-"
            bse_name = "-"
            qaqc_name = "-"
            status = "ASSIGNED"

            for spec in ENGINEER_ROLES:
                username = f"{spec['username_prefix']}{index}"
                password = f"{spec['password_prefix']}{index}"

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
                user.groups.add(groups[spec["group"]])
                role_assignments += 1

                profile, _ = UserProfile.objects.get_or_create(user=user)
                profile.designation = spec["designation"]
                profile.site_engineer_type = spec["profile_type"]
                profile.save(
                    update_fields=["designation", "site_engineer_type", "updated_at"]
                )

                if not authenticate(username=username, password=password):
                    failures.append(f"{username}: password verification failed")
                    status = "PARTIAL"

                users_cache[username] = user
                field = spec["project_field"]
                setattr(project, field, user)
                if spec["sync_m2m"]:
                    project.site_engineers.add(user)

                if spec["username_prefix"] == "pmc_se":
                    se_name = username
                elif spec["username_prefix"] == "pmc_bse":
                    bse_name = username
                elif spec["username_prefix"] == "pmc_qaqc":
                    qaqc_name = username

            project.save(
                update_fields=[
                    "site_engineer",
                    "billing_site_engineer",
                    "qaqc_site_engineer",
                    "updated_at",
                ]
            )
            projects_mapped += 1
            mapping_table.append(
                (index, project.name, tl_label, se_name, bse_name, qaqc_name, status, "")
            )

        self.stdout.write("")
        self.stdout.write("=" * 100)
        self.stdout.write(
            self.style.SUCCESS("PMC engineering team setup complete")
        )
        self.stdout.write("=" * 100)
        self.stdout.write(f"Users created:        {users_created}")
        self.stdout.write(f"Users updated:        {users_updated}")
        self.stdout.write(f"Role assignments:     {role_assignments}")
        self.stdout.write(f"Projects created:    {projects_created}")
        self.stdout.write(f"Projects mapped:      {projects_mapped}")
        self.stdout.write(f"Failed mappings:      {len(failures)}")

        self.stdout.write("")
        self.stdout.write("Verification counts (expected 23 each for mapped set):")
        for spec in ENGINEER_ROLES:
            count = User.objects.filter(
                username__regex=rf"^{spec['username_prefix']}[0-9]+$",
                groups__name=spec["group"],
            ).distinct().count()
            self.stdout.write(f"  {spec['group']:<25} {count}")

        tl_count = User.objects.filter(
            username__regex=r"^pmc_tl[0-9]+$",
            groups__name="Team Leader",
        ).distinct().count()
        self.stdout.write(f"  {'Team Leader':<25} {tl_count}")

        if failures:
            self.stdout.write("")
            self.stdout.write(self.style.ERROR("Failures:"))
            for item in failures:
                self.stdout.write(f"  - {item}")

        self.stdout.write("")
        self.stdout.write(
            f"{'#':<3} {'Project':<45} {'Team Leader':<12} {'Site Eng.':<12} "
            f"{'Billing SE':<12} {'QA/QC SE':<12} {'Status'}"
        )
        self.stdout.write("-" * 100)
        for row in mapping_table:
            idx, proj, tl, se, bse, qa, st, _ = row
            self.stdout.write(
                f"{idx:<3} {proj[:44]:<45} {tl:<12} {se:<12} {bse:<12} {qa:<12} {st}"
            )
        self.stdout.write("=" * 100)
