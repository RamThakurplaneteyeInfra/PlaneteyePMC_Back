import django.db.models.deletion
from django.db import migrations, models
import django.db.models.expressions


def backfill_scl(apps, schema_editor):
    PlannedEarnedValue = apps.get_model("planned_earned_value", "PlannedEarnedValue")
    PlannedEarnedValue.objects.filter(
        models.Q(planned_type__isnull=True) | models.Q(planned_type="")
    ).update(planned_type="SCL", contractor=None, contractor_name=None)
    PlannedEarnedValue.objects.filter(planned_type="SCL").update(
        contractor=None,
        contractor_name=None,
    )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("contractors", "0002_backfill_contractors"),
        ("planned_earned_value", "0005_alter_field_help_texts"),
    ]

    operations = [
        migrations.AddField(
            model_name="plannedearnedvalue",
            name="planned_type",
            field=models.CharField(
                choices=[("SCL", "SCL"), ("CONTRACTOR", "Contractor")],
                db_index=True,
                default="SCL",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="plannedearnedvalue",
            name="contractor",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="planned_vs_actual_records",
                to="contractors.contractor",
            ),
        ),
        migrations.AddField(
            model_name="plannedearnedvalue",
            name="contractor_name",
            field=models.CharField(
                blank=True,
                db_index=True,
                max_length=255,
                null=True,
            ),
        ),
        migrations.RunPython(backfill_scl, noop_reverse),
        migrations.RemoveConstraint(
            model_name="plannedearnedvalue",
            name="pev_unique_project_month_year",
        ),
        migrations.AlterModelOptions(
            name="plannedearnedvalue",
            options={
                "ordering": [
                    "project_name",
                    "year",
                    "month",
                    "planned_type",
                    "contractor_name",
                ],
                "verbose_name": "Planned vs Actual",
                "verbose_name_plural": "Planned vs Actual Records",
            },
        ),
        migrations.AddConstraint(
            model_name="plannedearnedvalue",
            constraint=models.UniqueConstraint(
                condition=models.Q(("planned_type", "SCL")),
                fields=("project_name", "planned_type", "month", "year"),
                name="pev_unique_scl_per_project_month",
            ),
        ),
        migrations.AddConstraint(
            model_name="plannedearnedvalue",
            constraint=models.UniqueConstraint(
                condition=models.Q(("planned_type", "CONTRACTOR")),
                fields=("project_name", "contractor", "month", "year"),
                name="pev_unique_contractor_per_project_month",
            ),
        ),
        migrations.AddIndex(
            model_name="plannedearnedvalue",
            index=models.Index(
                fields=["project_name", "planned_type", "year", "month"],
                name="pev_proj_type_period_idx",
            ),
        ),
    ]
