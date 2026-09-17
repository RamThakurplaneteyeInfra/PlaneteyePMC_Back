"""
Create AVISSA and SHIVALIKA projects with Team Leader, Site Engineer,
Billing Site Engineer, and QAQC Site Engineer assigned.

Run:
  python manage.py setup_avissa_shivalika
"""

from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import UserProfile
from projects.models import Project

PROJECTS = [
    {
        "name": "AVISSA",
        "index": 24,
        "tl": "pmc_tl24",
        "se": "pmc_se24",
        "bse": "pmc_bse24",
        "qaqc": "pmc_qaqc24",
        "hse": "pmc_hse24",
    },
    {
        "name": "SHIVALIKA",
        "index": 25,
        "tl": "pmc_tl25",
        "se": "pmc_se25",
        "bse": "pmc_bse25",
        "qaqc": "pmc_qaqc25",
        "hse": "pmc_hse25",
    },
]

ROLE_SPECS = {
    "tl": {
        "group": "Team Leader",
        "designation": "PMC Team Leader",
        "profile_type": None,
        "password_fn": lambda i: f"tl@{i}",
        "project_field": "team_lead",
        "sync_m2m": False,
    },
    "se": {
        "group": "Site Engineer",
        "designation": "Site Engineer",
        "profile_type": "site_engineer",
        "password_fn": lambda i: f"Pmc@SE{i}",
        "project_field": "site_engineer",
        "sync_m2m": True,
    },
    "bse": {
        "group": "Billing Site Engineer",
        "designation": "Billing Site Engineer",
        "profile_type": "billing_site_engineer",
        "password_fn": lambda i: f"Pmc@BSE{i}",
        "project_field": "billing_site_engineer",
        "sync_m2m": False,
    },
    "qaqc": {
        "group": "QAQC Site Engineer",
        "designation": "QA/QC Site Engineer",
        "profile_type": "qaqc_site_engineer",
        "password_fn": lambda i: f"Pmc@QA{i}",
        "project_field": "qaqc_site_engineer",
        "sync_m2m": False,
    },
    "hse": {
        "group": "HSE Site Engineer",
        "designation": "HSE Site Engineer",
        "profile_type": "hse_site_engineer",
        "password_fn": lambda i: f"Pmc@HSE{i}",
        "project_field": "hse_site_engineer",
        "sync_m2m": False,
    },
}


class Command(BaseCommand):
    help = "Create AVISSA and SHIVALIKA projects with full PMC engineering teams."

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()

        for proj_cfg in PROJECTS:
            project, created = Project.objects.get_or_create(
                name=proj_cfg["name"],
                defaults={"status": "active"},
            )
            if project.status != "active":
                project.status = "active"
                project.save(update_fields=["status", "updated_at"])

            self.stdout.write("")
            self.stdout.write(
                self.style.SUCCESS(
                    f"Project: {project.name} ({'created' if created else 'exists'})"
                )
            )

            for role_key in ("tl", "se", "bse", "qaqc", "hse"):
                spec = ROLE_SPECS[role_key]
                username = proj_cfg[role_key]
                password = spec["password_fn"](proj_cfg["index"])
                group, _ = Group.objects.get_or_create(name=spec["group"])

                user, user_created = User.objects.get_or_create(
                    username=username,
                    defaults={"is_active": True},
                )
                user.is_active = True
                user.set_password(password)
                user.save()
                user.groups.clear()
                user.groups.add(group)

                profile, _ = UserProfile.objects.get_or_create(user=user)
                profile.designation = spec["designation"]
                update_fields = ["designation", "updated_at"]
                if spec["profile_type"]:
                    profile.site_engineer_type = spec["profile_type"]
                    update_fields.append("site_engineer_type")
                profile.save(update_fields=update_fields)

                setattr(project, spec["project_field"], user)
                if spec["sync_m2m"]:
                    project.site_engineers.add(user)

                auth_ok = authenticate(username=username, password=password) is not None
                status = "OK" if auth_ok else "AUTH FAIL"
                self.stdout.write(
                    f"  {role_key.upper():4}  {username:<12}  "
                    f"pwd={password:<12}  id={user.id}  "
                    f"{'new' if user_created else 'updated'}  {status}"
                )

            project.save(
                update_fields=[
                    "team_lead",
                    "site_engineer",
                    "billing_site_engineer",
                    "qaqc_site_engineer",
                    "hse_site_engineer",
                    "updated_at",
                ]
            )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("AVISSA and SHIVALIKA setup complete."))
