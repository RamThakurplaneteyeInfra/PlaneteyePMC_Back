"""Migrate legacy ProjectDates.eot_date into ProjectEOT history (EOT #n)."""

from datetime import timedelta

from django.db import migrations


def forwards(apps, schema_editor):
    ProjectDates = apps.get_model("project_dates", "ProjectDates")
    ProjectEOT = apps.get_model("project_dates", "ProjectEOT")

    # Group by project — SCL first, then contractors by id
    rows = list(
        ProjectDates.objects.exclude(eot_date__isnull=True)
        .order_by("project_id", "date_type", "id")
    )
    by_project = {}
    for row in rows:
        by_project.setdefault(row.project_id, []).append(row)

    for project_id, pd_list in by_project.items():
        # Prefer unique revised dates; keep order
        seen_dates = set()
        number = 1
        for pd in pd_list:
            if pd.eot_date in seen_dates:
                continue
            seen_dates.add(pd.eot_date)
            contract = pd.contract_finish or pd.eot_date
            days = (pd.eot_date - contract).days
            if days <= 0:
                days = 1
            ProjectEOT.objects.create(
                project_id=project_id,
                project_dates_id=pd.id,
                eot_number=number,
                extension_days=days,
                original_completion_date=contract,
                revised_completion_date=pd.eot_date,
                approval_date=pd.eot_date,
                reason="Migrated from legacy ProjectDates.eot_date",
                remarks="",
                status="approved",
                is_active=True,
            )
            number += 1


def backwards(apps, schema_editor):
    ProjectEOT = apps.get_model("project_dates", "ProjectEOT")
    ProjectEOT.objects.filter(
        reason="Migrated from legacy ProjectDates.eot_date"
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("project_dates", "0008_projecteot_multi_eot"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
