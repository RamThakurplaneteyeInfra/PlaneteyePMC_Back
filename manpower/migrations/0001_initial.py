from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="ProjectManpower",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("project_name", models.CharField(db_index=True, max_length=255)),
                ("month_year", models.CharField(db_index=True, max_length=12)),
                ("planned_manpower", models.PositiveIntegerField()),
                ("actual_manpower", models.PositiveIntegerField()),
                ("working_hours_per_day", models.FloatField()),
                ("working_days_per_month", models.PositiveIntegerField()),
                ("planned_mh", models.FloatField(default=0)),
                ("actual_mh", models.FloatField(default=0)),
                ("planned_mh_cumulative", models.FloatField(default=0)),
                ("actual_mh_cumulative", models.FloatField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Project manpower (monthly)",
                "verbose_name_plural": "Project manpower records",
                "ordering": ["project_name", "month_year"],
            },
        ),
        migrations.AddConstraint(
            model_name="projectmanpower",
            constraint=models.UniqueConstraint(
                fields=("project_name", "month_year"),
                name="manpower_unique_project_month_year",
            ),
        ),
    ]
