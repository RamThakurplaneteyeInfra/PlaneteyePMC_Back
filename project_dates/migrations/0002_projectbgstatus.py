# Generated manually for ProjectBGStatus

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0001_initial"),
        ("project_dates", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProjectBGStatus",
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
                    "contractor_bg_date",
                    models.DateField(
                        blank=True,
                        help_text="Contractor bank guarantee date (optional)",
                        null=True,
                    ),
                ),
                (
                    "scl_bg_date",
                    models.DateField(
                        blank=True,
                        help_text="SCL bank guarantee date (optional)",
                        null=True,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "project",
                    models.OneToOneField(
                        help_text="Project this BG status belongs to",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="bg_status_record",
                        to="projects.project",
                    ),
                ),
            ],
            options={
                "verbose_name": "Project BG Status",
                "verbose_name_plural": "Project BG Status Records",
            },
        ),
    ]
