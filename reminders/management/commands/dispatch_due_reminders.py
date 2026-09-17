from django.core.management.base import BaseCommand

from reminders.services import dispatch_due_reminders


class Command(BaseCommand):
    help = (
        "Dispatch due project reminders to assignees via Alerts + WebSocket. "
        "Schedule via Railway cron every 1–5 minutes."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=500,
            help="Max reminders to process in one run (default 500).",
        )

    def handle(self, *args, **options):
        summary = dispatch_due_reminders(limit=options["limit"])
        self.stdout.write(self.style.SUCCESS(f"Reminders dispatch: {summary}"))
