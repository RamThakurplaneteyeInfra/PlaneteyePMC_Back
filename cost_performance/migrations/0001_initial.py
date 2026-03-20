from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="ProjectCostPerformance",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("project_name", models.CharField(db_index=True, max_length=255)),
                ("month_year", models.CharField(db_index=True, max_length=12)),
                ("bcws", models.FloatField(help_text="Budgeted Cost of Work Scheduled (planned cost)")),
                ("bcwp", models.FloatField(help_text="Budgeted Cost of Work Performed (earned value)")),
                ("acwp", models.FloatField(help_text="Actual Cost of Work Performed")),
                ("fcst", models.FloatField(help_text="Forecast cost of remaining work")),
                ("eac", models.FloatField(default=0, help_text="EAC = ACWP + FCST")),
                ("cv", models.FloatField(default=0, help_text="CV = BCWP - ACWP")),
                ("sv", models.FloatField(default=0, help_text="SV = BCWP - BCWS")),
                (
                    "bac",
                    models.FloatField(
                        blank=True,
                        help_text="Budget at completion (optional; used for VAC)",
                        null=True,
                    ),
                ),
                ("cpi", models.FloatField(blank=True, help_text="CPI = BCWP/ACWP", null=True)),
                ("vac", models.FloatField(blank=True, help_text="VAC = BAC - EAC when BAC set", null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Project cost performance",
                "verbose_name_plural": "Project cost performance records",
                "ordering": ["project_name", "month_year"],
            },
        ),
        migrations.AddConstraint(
            model_name="projectcostperformance",
            constraint=models.UniqueConstraint(
                fields=("project_name", "month_year"),
                name="costperf_unique_project_month_year",
            ),
        ),
    ]
