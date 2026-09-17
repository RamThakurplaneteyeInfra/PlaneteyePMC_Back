"""
Create PMC Team Leader user accounts (Django group: Team Leader).

Safe to re-run: existing usernames get password/role refreshed; no duplicates.

Run:
  python manage.py create_pmc_team_leaders
  py -3.11 manage.py create_pmc_team_leaders
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from accounts.models import UserProfile

# Canonical role in the PMC auth system (Group name used by JWT / permissions).
TEAM_LEADER_GROUP = "Team Leader"
PMC_TEAM_LEADER_DESIGNATION = "PMC Team Leader"

PMC_TEAM_LEADERS = [
    ("pmc_tl1", "tl@1"),
    ("pmc_tl2", "tl@2"),
    ("pmc_tl3", "tl@3"),
    ("pmc_tl4", "tl@4"),
    ("pmc_tl5", "tl@5"),
    ("pmc_tl6", "tl@6"),
    ("pmc_tl7", "tl@7"),
    ("pmc_tl8", "tl@8"),
    ("pmc_tl9", "tl@9"),
    ("pmc_tl10", "tl@10"),
    ("pmc_tl11", "tl@11"),
    ("pmc_tl12", "tl@12"),
    ("pmc_tl13", "tl@13"),
]


class Command(BaseCommand):
    help = (
        "Create or update PMC Team Leader accounts (Team Leader role). "
        "Idempotent — safe to run multiple times."
    )

    def handle(self, *args, **options):
        User = get_user_model()
        group, _ = Group.objects.get_or_create(name=TEAM_LEADER_GROUP)

        created_count = 0
        updated_count = 0
        processed_usernames = []

        for username, password in PMC_TEAM_LEADERS:
            user, is_created = User.objects.get_or_create(
                username=username,
                defaults={"is_active": True},
            )

            if is_created:
                created_count += 1
                action = "created"
            else:
                updated_count += 1
                action = "updated"

            user.is_active = True
            user.set_password(password)
            user.save()

            user.groups.clear()
            user.groups.add(group)

            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.designation = PMC_TEAM_LEADER_DESIGNATION
            profile.save(update_fields=["designation", "updated_at"])

            processed_usernames.append(username)
            self.stdout.write(
                self.style.SUCCESS(
                    f"[OK] {username} -> {TEAM_LEADER_GROUP} ({action})"
                )
            )

        self.stdout.write("")
        self.stdout.write("=" * 60)
        self.stdout.write(
            self.style.SUCCESS(
                f"PMC Team Leader provisioning complete.\n"
                f"Total accounts created: {created_count}\n"
                f"Total accounts updated: {updated_count}\n"
                f"Total processed: {len(processed_usernames)}"
            )
        )
        self.stdout.write("Usernames processed:")
        for name in processed_usernames:
            self.stdout.write(f"  - {name}")
        self.stdout.write("=" * 60)
