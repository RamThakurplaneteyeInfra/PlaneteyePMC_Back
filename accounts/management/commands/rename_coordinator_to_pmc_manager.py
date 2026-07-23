"""
Rename Coordinator role to PMC Manager and pmc_coordinator to pmc_manager.

Run:
  python manage.py rename_coordinator_to_pmc_manager
  python manage.py rename_coordinator_to_pmc_manager --dry-run
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction

User = get_user_model()

OLD_GROUP = "Coordinator"
NEW_GROUP = "PMC Manager"
OLD_USERNAME = "pmc_coordinator"
NEW_USERNAME = "pmc_manager"


class Command(BaseCommand):
    help = "Rename Coordinator group/role to PMC Manager and migrate demo user"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print actions without writing changes",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        dry = options["dry_run"]
        if dry:
            self.stdout.write(self.style.WARNING("DRY RUN - no changes will be saved"))

        # 1) Group rename / merge
        old_group = Group.objects.filter(name=OLD_GROUP).first()
        new_group, created = Group.objects.get_or_create(name=NEW_GROUP)
        if created:
            self.stdout.write(self.style.SUCCESS(f"Created group: {NEW_GROUP}"))
        else:
            self.stdout.write(f"Group already exists: {NEW_GROUP}")

        moved = 0
        if old_group:
            for user in list(old_group.user_set.all()):
                if not user.groups.filter(name=NEW_GROUP).exists():
                    if not dry:
                        user.groups.add(new_group)
                    moved += 1
                    self.stdout.write(f"  Moved user '{user.username}' -> {NEW_GROUP}")
                if not dry:
                    user.groups.remove(old_group)
            if not dry:
                old_group.delete()
            self.stdout.write(
                self.style.SUCCESS(
                    f"Migrated {moved} user(s) from '{OLD_GROUP}' and removed old group"
                )
            )
        else:
            self.stdout.write(f"No '{OLD_GROUP}' group found (already migrated?)")

        # 2) Username migrate
        old_user = User.objects.filter(username=OLD_USERNAME).first()
        new_user = User.objects.filter(username=NEW_USERNAME).first()

        if old_user and new_user and old_user.pk != new_user.pk:
            # Both exist (create_demo_users already made pmc_manager).
            # Transfer project assignments, ensure role, deactivate old user.
            try:
                from projects.models import Project

                for project in Project.objects.filter(coordinators=old_user):
                    if not dry:
                        project.coordinators.add(new_user)
                        project.coordinators.remove(old_user)
                    self.stdout.write(
                        f"  Transferred project '{project.name}' coordinator assignment"
                    )
            except Exception as exc:
                self.stdout.write(self.style.WARNING(f"Project transfer skipped: {exc}"))

            if not dry:
                if not new_user.groups.filter(name=NEW_GROUP).exists():
                    new_user.groups.add(new_group)
                old_user.is_active = False
                old_user.save(update_fields=["is_active"])
            self.stdout.write(
                self.style.SUCCESS(
                    f"Kept '{NEW_USERNAME}', deactivated '{OLD_USERNAME}'"
                )
            )
        elif old_user and not new_user:
            if not dry:
                old_user.username = NEW_USERNAME
                old_user.save(update_fields=["username"])
                if not old_user.groups.filter(name=NEW_GROUP).exists():
                    old_user.groups.add(new_group)
            self.stdout.write(
                self.style.SUCCESS(f"Renamed user '{OLD_USERNAME}' -> '{NEW_USERNAME}'")
            )
        elif new_user:
            if not new_user.groups.filter(name=NEW_GROUP).exists():
                if not dry:
                    new_user.groups.add(new_group)
                self.stdout.write(
                    self.style.SUCCESS(f"Assigned '{NEW_USERNAME}' to group {NEW_GROUP}")
                )
            else:
                self.stdout.write(f"User '{NEW_USERNAME}' already has {NEW_GROUP}")
        else:
            self.stdout.write(
                f"Neither '{OLD_USERNAME}' nor '{NEW_USERNAME}' found "
                f"(run create_demo_users to create '{NEW_USERNAME}')"
            )

        # 3) DPR current_approver_role migration
        try:
            from dpr.models import DailyProgressReport

            qs = DailyProgressReport.objects.filter(current_approver_role=OLD_GROUP)
            count = qs.count()
            if count and not dry:
                qs.update(current_approver_role=NEW_GROUP)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Updated {count} DPR row(s) current_approver_role "
                    f"'{OLD_GROUP}' -> '{NEW_GROUP}'"
                )
            )
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f"DPR role migration skipped: {exc}"))

        if dry:
            transaction.set_rollback(True)
            self.stdout.write(self.style.WARNING("DRY RUN complete - rolled back"))
        else:
            self.stdout.write(
                self.style.SUCCESS("Coordinator -> PMC Manager migration complete")
            )
