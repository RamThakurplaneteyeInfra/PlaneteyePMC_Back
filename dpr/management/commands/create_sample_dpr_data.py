"""
Management command to create sample DPR data for Thane Project
Run: python manage.py create_sample_dpr_data
"""
from datetime import date
from django.core.management.base import BaseCommand
from dpr.models import DailyProgressReport, DPRActivity


class Command(BaseCommand):
    help = 'Create sample DPR data for Thane Project'

    def handle(self, *args, **options):
        # Clear existing Thane Project data
        deleted, _ = DailyProgressReport.objects.filter(
            project_name__icontains='Thane'
        ).delete()
        self.stdout.write(f'Deleted {deleted} existing records')

        project_name = 'Thane Project'
        job_no = 'THN-2026-001'

        dpr_data = [
            # Week 1 (Mar 16-22)
            (date(2026, 3, 16), 'Site clearing and mobilization', 100.0),
            (date(2026, 3, 17), 'Excavation work - Phase 1', 80.0),
            (date(2026, 3, 18), 'Excavation completed', 100.0),
            (date(2026, 3, 19), 'Foundation marking and setting', 60.0),
            (date(2026, 3, 20), 'Rebar binding - Section A', 40.0),
            (date(2026, 3, 21), 'Rebar binding completed', 100.0),
            (date(2026, 3, 22), 'Concrete pouring - Foundation', 35.0),
            # Week 2 (Mar 23-29)
            (date(2026, 3, 23), 'Concrete curing', 100.0),
            (date(2026, 3, 24), 'Formwork removal', 70.0),
            (date(2026, 3, 25), 'Quality inspection', 100.0),
            (date(2026, 3, 26), 'Brick masonry - Ground floor', 25.0),
            (date(2026, 3, 27), 'Brick masonry continued', 50.0),
            (date(2026, 3, 28), 'Plumbing rough-in', 30.0),
            (date(2026, 3, 29), 'Electrical conduit laying', 20.0),
            # Week 3 (Mar 30 - Apr 3)
            (date(2026, 3, 30), 'Brick masonry completion', 100.0),
            (date(2026, 3, 31), 'Plumbing fixtures installation', 40.0),
            (date(2026, 4, 1), 'Electrical wiring', 35.0),
            (date(2026, 4, 2), 'Plastering work', 15.0),
            (date(2026, 4, 3), 'Ceiling false work', 10.0),
        ]

        for d, a, t in dpr_data:
            dpr = DailyProgressReport.objects.create(
                project_name=project_name,
                job_no=job_no,
                report_date=d,
                unresolved_issues='Minor delay in material delivery',
                quality_status='All quality checks passed',
                bill_status='Submitted',
                gfc_status='Approved',
                issued_by='Site Engineer',
                designation='Junior Engineer',
                status='approved'
            )
            DPRActivity.objects.create(
                dpr=dpr,
                date=d,
                activity=a,
                target_achieved=t,
                deliverables='As per schedule',
                next_day_plan='Continue work as planned',
                remarks='Progress on track'
            )
            self.stdout.write(f'Created: {d} - {a}')

        self.stdout.write(
            self.style.SUCCESS(
                f'Successfully created {len(dpr_data)} DPRs for {project_name}'
            )
        )