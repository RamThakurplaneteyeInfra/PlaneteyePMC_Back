"""
Create dev/test login users for the PMC app.

Run:
  python manage.py create_demo_users
  python manage.py create_demo_users --password pass12345
"""

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from accounts.models import UserProfile

DEFAULT_DEMO_PASSWORD = "Project@123"


class Command(BaseCommand):
    help = "Create demo users for every PMC role and assign them to role groups"

    DEMO_USERS = [
        {"username": "pmc_ceo", "group": "CEO", "site_engineer_type": None},
        {"username": "pmc_head", "group": "PMC Head", "site_engineer_type": None},
        {"username": "pmc_ho", "group": "Head Office", "site_engineer_type": None},
        {"username": "pmc_manager", "group": "PMC Manager", "site_engineer_type": None},
        {"username": "pmc_tl", "group": "Team Leader", "site_engineer_type": None},
        {
            "username": "pmc_se",
            "group": "Site Engineer",
            "site_engineer_type": "site_engineer",
        },
        {
            "username": "pmc_bse",
            "group": "Billing Site Engineer",
            "site_engineer_type": "billing_site_engineer",
        },
        {
            "username": "pmc_qaqc",
            "group": "QAQC Site Engineer",
            "site_engineer_type": "qaqc_site_engineer",
        },
        {
            "username": "pmc_hse",
            "group": "HSE Site Engineer",
            "site_engineer_type": "hse_site_engineer",
        },
    ]

    def add_arguments(self, parser):
        parser.add_argument(
            "--password",
            default=DEFAULT_DEMO_PASSWORD,
            help=f"Password for all demo users (default: {DEFAULT_DEMO_PASSWORD})",
        )

    def handle(self, *args, **options):
        User = get_user_model()
        password = options["password"]

        created = 0
        updated = 0
        for u in self.DEMO_USERS:
            username = u["username"]
            group_name = u["group"]
            site_engineer_type = u["site_engineer_type"]

            group, _ = Group.objects.get_or_create(name=group_name)

            user, is_created = User.objects.get_or_create(
                username=username,
                defaults={"is_active": True},
            )

            if is_created:
                created += 1
            else:
                updated += 1

            # Never delete users or other fields — only activate and set password.
            user.is_active = True
            user.set_password(password)
            user.save(update_fields=["password", "is_active"])

            # Keep this demo username on its single canonical role group.
            user.groups.set([group])

            profile, _ = UserProfile.objects.get_or_create(user=user)
            if profile.site_engineer_type != site_engineer_type:
                profile.site_engineer_type = site_engineer_type
                profile.save(update_fields=["site_engineer_type", "updated_at"])

            self.stdout.write(
                self.style.SUCCESS(f"[OK] {username} -> {group_name}")
            )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Created: {created}, Updated: {updated}. Password: {password}"
            )
        )
