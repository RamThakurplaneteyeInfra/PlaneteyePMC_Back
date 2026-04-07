"""
Create dev/test login users for the PMC app.

Run:
  python manage.py create_demo_users

This seeds users with password "123" and assigns them to the correct Django Groups.
"""

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from accounts.models import UserProfile


class Command(BaseCommand):
    help = "Create demo users (password=123) and assign them to role groups"

    DEMO_USERS = [
        {"username": "pmc_head", "password": "Project@123", "group": "PMC Head", "site_engineer_type": None},
        {"username": "pmc_coordinator", "password": "coordinator@123", "group": "Coordinator", "site_engineer_type": None},
        {"username": "pmc_tl", "password": "tl@123", "group": "Team Leader", "site_engineer_type": None},
        {
            "username": "pmc_bse",
            "password": "bse@123",
            "group": "Billing Site Engineer",
            "site_engineer_type": "billing_site_engineer",
        },
        {
            "username": "pmc_se",
            "password": "se@123",
            "group": "Site Engineer",
            "site_engineer_type": "site_engineer",
        },
        {
            "username": "pmc_qaqc",
            "password": "qaqc@123",
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
            password = u["password"]
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

            # Ensure password and active status are correct for login tests
            user.is_active = True
            user.set_password(password)
            user.save()

            # Assign role group(s)
            user.groups.clear()
            user.groups.add(group)

            # Assign subtype for site engineer roles (for API/profile display)
            if site_engineer_type:
                profile, _ = UserProfile.objects.get_or_create(user=user)
                profile.site_engineer_type = site_engineer_type
                profile.save()

            self.stdout.write(self.style.SUCCESS(f"[OK] {username} -> {group_name}"))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Done. Created: {created}, Updated: {updated}"))

