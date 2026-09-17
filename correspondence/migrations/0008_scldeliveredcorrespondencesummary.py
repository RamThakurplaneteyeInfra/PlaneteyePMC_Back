from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("correspondence", "0007_remove_correspondencedocument_corr_doc_received_idx_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="SCLDeliveredCorrespondenceSummary",
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
                ("project_name", models.CharField(db_index=True, max_length=255)),
                ("month", models.PositiveSmallIntegerField(db_index=True)),
                ("year", models.PositiveSmallIntegerField(db_index=True)),
                (
                    "view",
                    models.CharField(
                        choices=[
                            ("monthly", "Monthly"),
                            ("cumulative", "Cumulative"),
                        ],
                        db_index=True,
                        default="monthly",
                        max_length=20,
                    ),
                ),
                ("client", models.PositiveIntegerField(default=0)),
                ("contractor", models.PositiveIntegerField(default=0)),
                ("other_agency", models.PositiveIntegerField(default=0)),
                (
                    "created_at",
                    models.DateTimeField(
                        default=django.utils.timezone.now, editable=False
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "SCL Delivered Correspondence Summary",
                "verbose_name_plural": "SCL Delivered Correspondence Summaries",
                "ordering": ["-year", "-month", "project_name"],
            },
        ),
        migrations.AddConstraint(
            model_name="scldeliveredcorrespondencesummary",
            constraint=models.UniqueConstraint(
                fields=("project_name", "year", "month", "view"),
                name="scl_delivered_unique_project_period_view",
            ),
        ),
    ]
