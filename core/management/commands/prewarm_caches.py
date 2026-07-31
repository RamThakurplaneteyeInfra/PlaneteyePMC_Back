"""Rebuild hot caches after deploy / Redis restart."""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Pre-warm project overview, dropdown, and other hot caches."

    def handle(self, *args, **options):
        from core.tasks import prewarm_project_caches

        result = prewarm_project_caches()
        self.stdout.write(self.style.SUCCESS(f"Prewarm complete: {result}"))
