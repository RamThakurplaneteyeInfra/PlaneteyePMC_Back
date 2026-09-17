"""
Update passwords for PMC Team Leader accounts (pmc_tl1–pmc_tl23) only.

Does not change usernames, roles, profiles, or project assignments.

Run:
  py -3.11 manage.py update_pmc_team_leader_passwords
"""

from django.contrib.auth import authenticate, get_user_model
from django.core.management.base import BaseCommand

PASSWORD_UPDATES = {f"pmc_tl{i}": f"Pmc@TL{i}" for i in range(1, 24)}


class Command(BaseCommand):
    help = (
        "Update passwords for pmc_tl1–pmc_tl23 using Django set_password(). "
        "Usernames, roles, and project assignments are not modified."
    )

    def handle(self, *args, **options):
        User = get_user_model()

        missing_users: list[str] = []
        failed_updates: list[str] = []
        passwords_updated = 0
        processed_usernames: list[str] = []

        for username, new_password in PASSWORD_UPDATES.items():
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                missing_users.append(username)
                self.stdout.write(
                    self.style.WARNING(f"[MISSING] {username} - user not found, skipped")
                )
                continue

            processed_usernames.append(username)

            try:
                user.set_password(new_password)
                user.save(update_fields=["password"])
            except Exception as exc:
                failed_updates.append(f"{username}: {exc}")
                self.stdout.write(
                    self.style.ERROR(f"[FAIL] {username} - password update failed: {exc}")
                )
                continue

            if not authenticate(username=username, password=new_password):
                failed_updates.append(f"{username}: authentication verification failed")
                self.stdout.write(
                    self.style.ERROR(
                        f"[FAIL] {username} - could not authenticate with new password"
                    )
                )
                continue

            passwords_updated += 1
            self.stdout.write(self.style.SUCCESS(f"[OK] {username} - password updated"))

        self.stdout.write("")
        self.stdout.write("=" * 60)
        self.stdout.write(
            self.style.SUCCESS("PMC Team Leader password update complete")
        )
        self.stdout.write("=" * 60)
        self.stdout.write(f"Total users processed:  {len(processed_usernames)}")
        self.stdout.write(f"Total passwords updated: {passwords_updated}")
        self.stdout.write(f"Missing users:          {len(missing_users)}")
        self.stdout.write(f"Failed updates:         {len(failed_updates)}")

        if missing_users:
            self.stdout.write("")
            self.stdout.write("Missing usernames:")
            for name in missing_users:
                self.stdout.write(f"  - {name}")

        if failed_updates:
            self.stdout.write("")
            self.stdout.write(self.style.ERROR("Failed updates:"))
            for item in failed_updates:
                self.stdout.write(f"  - {item}")

        self.stdout.write("=" * 60)
