"""Add contractor_name and support multiple contractor schedules per project."""

from django.db import migrations, models
from django.db.models import Q


def backfill_contractor_names(apps, schema_editor):
    ProjectDates = apps.get_model("project_dates", "ProjectDates")
    for row in ProjectDates.objects.filter(date_type="CONTRACTOR"):
        if not (row.contractor_name or "").strip():
            row.contractor_name = "Contractor"
            row.save(update_fields=["contractor_name"])


class Migration(migrations.Migration):

    dependencies = [
        ("project_dates", "0004_bgstatus_multi_entry"),
    ]

    operations = [
        migrations.AddField(
            model_name="projectdates",
            name="contractor_name",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="Contractor display name (required for CONTRACTOR rows; null for SCL)",
                max_length=255,
                null=True,
            ),
        ),
        migrations.RunPython(backfill_contractor_names, migrations.RunPython.noop),
        migrations.AlterUniqueTogether(
            name="projectdates",
            unique_together=set(),
        ),
        migrations.AddConstraint(
            model_name="projectdates",
            constraint=models.UniqueConstraint(
                fields=("project", "date_type"),
                condition=Q(date_type="SCL"),
                name="pd_unique_scl_per_project",
            ),
        ),
        migrations.AddConstraint(
            model_name="projectdates",
            constraint=models.UniqueConstraint(
                fields=("project", "contractor_name"),
                condition=Q(date_type="CONTRACTOR"),
                name="pd_unique_contractor_name_per_project",
            ),
        ),
        migrations.AddIndex(
            model_name="projectdates",
            index=models.Index(
                fields=["project", "contractor_name"],
                name="pd_project_contractor_idx",
            ),
        ),
    ]
