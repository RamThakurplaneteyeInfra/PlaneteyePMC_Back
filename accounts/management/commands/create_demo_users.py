"""
Create dev/test login users for the PMC app.

All demo accounts use the same password as the frontend login form: Project@123

Run:
  python manage.py create_demo_users
"""

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from accounts.models import UserProfile

# Shared with frontend login (all role-based demo users)
DEFAULT_DEMO_PASSWORD = "Project@123"


class Command(BaseCommand):
    help = (
        "Create demo users (password=Project@123 for all) "
        "and assign them to role groups"
    )

    DEMO_USERS = [
        {"username": "pmc_head", "group": "PMC Head", "site_engineer_type": None},
        {"username": "pmc_ho", "group": "Head Office", "site_engineer_type": None},
        {"username": "pmc_manager", "group": "PMC Manager", "site_engineer_type": None},
        {"username": "pmc_tl", "group": "Team Leader", "site_engineer_type": None},
        {
            "username": "pmc_bse",
            "group": "Billing Site Engineer",
            "site_engineer_type": "billing_site_engineer",
        },
        {
            "username": "pmc_se",
            "group": "Site Engineer",
            "site_engineer_type": "site_engineer",
        },
        {
            "username": "pmc_qaqc",
            "group": "QAQC Site Engineer",
            "site_engineer_type": "qaqc_site_engineer",
        },
    ]

    def handle(self, *args, **options):
        User = get_user_model()

        created = 0
        updated = 0
        for u in self.DEMO_USERS:
            username = u["username"]
            group_name = u["group"]
            site_engineer_type = u["site_engineer_type"]

            group, _ = Group.objects.get_or_create(name=group_name)

            user, is_created = User.objects.get_or_create(
                username=username,
                defaults={
                    "is_active": True,
                },
            )

            if is_created:
                created += 1
            else:
                updated += 1

            user.is_active = True
            user.set_password(DEFAULT_DEMO_PASSWORD)
            user.save()

            user.groups.clear()
            user.groups.add(group)

            if site_engineer_type:
                profile, _ = UserProfile.objects.get_or_create(user=user)
                profile.site_engineer_type = site_engineer_type
                profile.save()

            self.stdout.write(
                self.style.SUCCESS(
                    f"[OK] {username} -> {group_name} (password: {DEFAULT_DEMO_PASSWORD})"
                )
            )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(f"Done. Created: {created}, Updated: {updated}")
        )
