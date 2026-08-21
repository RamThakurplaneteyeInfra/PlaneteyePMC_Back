from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_date

from dpr.services.executive_digest import send_dpr_executive_digest


class Command(BaseCommand):
    help = (
        "Send the DPR executive digest to PMC Head and Head Office. "
        "Intended schedule: 15:30 IST (10:00 UTC) via external scheduler "
        "POST /api/internal/dpr/executive-digest/. "
        "This command shares the same service as that endpoint."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=str,
            default=None,
            help="Report date YYYY-MM-DD (default: today Asia/Kolkata).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Build digest without sending email (skips idempotency).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Bypass completed/running idempotency for the report date.",
        )

    def handle(self, *args, **options):
        report_date = None
        raw = options.get("date")
        if raw:
            report_date = parse_date(raw)
            if report_date is None:
                raise CommandError(f"Invalid --date value: {raw!r} (use YYYY-MM-DD)")

        summary = send_dpr_executive_digest(
            report_date=report_date,
            dry_run=bool(options.get("dry_run")),
            force=bool(options.get("force")),
            source="management_command",
        )
        self.stdout.write(self.style.SUCCESS(f"DPR executive digest: {summary}"))
