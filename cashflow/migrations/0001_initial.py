from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="CashFlow",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("project_name", models.CharField(db_index=True, max_length=255)),
                ("month_year", models.CharField(db_index=True, max_length=12)),
                ("cash_in_monthly_plan", models.FloatField()),
                ("cash_in_monthly_actual", models.FloatField()),
                ("cash_out_monthly_plan", models.FloatField()),
                ("cash_out_monthly_actual", models.FloatField()),
                ("actual_cost_monthly", models.FloatField()),
                ("cash_in_cumulative_plan", models.FloatField(default=0)),
                ("cash_in_cumulative_actual", models.FloatField(default=0)),
                ("cash_out_cumulative_plan", models.FloatField(default=0)),
                ("cash_out_cumulative_actual", models.FloatField(default=0)),
                ("actual_cost_cumulative", models.FloatField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Cash flow (monthly)",
                "verbose_name_plural": "Cash flow records",
                "ordering": ["project_name", "month_year"],
            },
        ),
        migrations.AddConstraint(
            model_name="cashflow",
            constraint=models.UniqueConstraint(
                fields=("project_name", "month_year"),
                name="cashflow_unique_project_month_year",
            ),
        ),
    ]
