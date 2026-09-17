# Multi-entry BG Status model + legacy ProjectBGStatus data migration

from django.db import migrations, models
import django.db.models.deletion


def migrate_legacy_project_bg_status(apps, schema_editor):
    """Copy single-row ProjectBGStatus dates into BGStatus entries."""
    ProjectBGStatus = apps.get_model("project_dates", "ProjectBGStatus")
    BGStatus = apps.get_model("project_dates", "BGStatus")
    ProjectDates = apps.get_model("project_dates", "ProjectDates")

    for legacy in ProjectBGStatus.objects.select_related("project").iterator():
        project_id = legacy.project_id

        contractor_due = legacy.contractor_bg_due_date
        contractor_updated = legacy.contractor_bg_updated_date
        if contractor_due or contractor_updated:
            project_date = ProjectDates.objects.filter(
                project_id=project_id,
                date_type="CONTRACTOR",
            ).first()
            if project_date:
                due = contractor_due or contractor_updated
                BGStatus.objects.create(
                    project_date_id=project_date.id,
                    bg_type="CONTRACTOR",
                    bg_name="Contractor BG (Migrated)",
                    due_date=due,
                    updated_date=contractor_updated,
                )

        scl_due = legacy.scl_bg_due_date
        scl_updated = legacy.scl_bg_updated_date
        if scl_due or scl_updated:
            project_date = ProjectDates.objects.filter(
                project_id=project_id,
                date_type="SCL",
            ).first()
            if project_date:
                due = scl_due or scl_updated
                BGStatus.objects.create(
                    project_date_id=project_date.id,
                    bg_type="SCL",
                    bg_name="SCL BG (Migrated)",
                    due_date=due,
                    updated_date=scl_updated,
                )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("project_dates", "0003_projectbgstatus_bg_due_dates"),
    ]

    operations = [
        migrations.CreateModel(
            name="BGStatus",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "bg_type",
                    models.CharField(
                        choices=[
                            ("CONTRACTOR", "Contractor"),
                            ("SCL", "SCL"),
                        ],
                        db_index=True,
                        help_text="Contractor or SCL bank guarantee",
                        max_length=20,
                    ),
                ),
                (
                    "bg_name",
                    models.CharField(
                        help_text="Display name for this bank guarantee",
                        max_length=255,
                    ),
                ),
                (
                    "due_date",
                    models.DateField(help_text="Bank guarantee due date"),
                ),
                (
                    "updated_date",
                    models.DateField(
                        blank=True,
                        help_text="Date the bank guarantee was last updated",
                        null=True,
                    ),
                ),
                (
                    "remarks",
                    models.TextField(blank=True, help_text="Optional notes"),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "project_date",
                    models.ForeignKey(
                        help_text="Parent project dates record (SCL or CONTRACTOR)",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="bg_statuses",
                        to="project_dates.projectdates",
                    ),
                ),
            ],
            options={
                "verbose_name": "BG Status",
                "verbose_name_plural": "BG Status Entries",
                "ordering": ["id"],
            },
        ),
        migrations.AddIndex(
            model_name="bgstatus",
            index=models.Index(
                fields=["project_date", "bg_type"],
                name="pd_bg_project_date_type_idx",
            ),
        ),
        migrations.RunPython(migrate_legacy_project_bg_status, noop_reverse),
        migrations.AlterModelOptions(
            name="projectbgstatus",
            options={
                "verbose_name": "Project BG Status (Deprecated)",
                "verbose_name_plural": "Project BG Status Records (Deprecated)",
            },
        ),
    ]
