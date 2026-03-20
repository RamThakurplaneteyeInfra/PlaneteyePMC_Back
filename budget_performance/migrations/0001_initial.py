# Generated manually for BudgetCostPerformance

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="BudgetCostPerformance",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("project_name", models.CharField(db_index=True, max_length=255)),
                (
                    "bac",
                    models.DecimalField(
                        decimal_places=4,
                        help_text="Budget at Completion (BAC)",
                        max_digits=24,
                    ),
                ),
                (
                    "bcwp",
                    models.DecimalField(
                        decimal_places=4,
                        help_text="Earned Value / BCWP",
                        max_digits=24,
                    ),
                ),
                (
                    "acwp",
                    models.DecimalField(
                        decimal_places=4,
                        help_text="Actual Cost / ACWP",
                        max_digits=24,
                    ),
                ),
                (
                    "cpi",
                    models.DecimalField(
                        decimal_places=6,
                        help_text="Cost Performance Index = BCWP / ACWP",
                        max_digits=24,
                    ),
                ),
                (
                    "eac",
                    models.DecimalField(
                        decimal_places=4,
                        help_text="Estimate at Completion = BAC / CPI",
                        max_digits=24,
                    ),
                ),
                (
                    "etg",
                    models.DecimalField(
                        decimal_places=4,
                        help_text="Estimate to Go = EAC - ACWP",
                        max_digits=24,
                    ),
                ),
                (
                    "vac",
                    models.DecimalField(
                        decimal_places=4,
                        help_text="Variance at Completion = BAC - EAC",
                        max_digits=24,
                    ),
                ),
                (
                    "cv",
                    models.DecimalField(
                        decimal_places=4,
                        help_text="Cost Variance = BCWP - ACWP",
                        max_digits=24,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Budget Cost Performance",
                "verbose_name_plural": "Budget Cost Performance Records",
                "ordering": ["-created_at"],
            },
        ),
    ]
