from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="ProjectEquipment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("project_name", models.CharField(db_index=True, max_length=255)),
                ("month", models.DateField(help_text="First day of the month for this record")),
                ("planned_equipment", models.PositiveIntegerField()),
                ("actual_equipment", models.PositiveIntegerField()),
                ("planned_cumulative", models.PositiveIntegerField(default=0)),
                ("actual_cumulative", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Project equipment (monthly)",
                "verbose_name_plural": "Project equipment records",
                "ordering": ["project_name", "month"],
            },
        ),
        migrations.AddConstraint(
            model_name="projectequipment",
            constraint=models.UniqueConstraint(
                fields=("project_name", "month"),
                name="equipment_unique_project_month",
            ),
        ),
    ]
