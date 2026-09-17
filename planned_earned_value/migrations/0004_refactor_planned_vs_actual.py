import django.db.models.deletion
from decimal import Decimal, ROUND_HALF_UP
from django.conf import settings
from django.db import migrations, models
import django.utils.timezone


def forwards_migrate(apps, schema_editor):
    PlannedEarnedValue = apps.get_model("planned_earned_value", "PlannedEarnedValue")
    Project = apps.get_model("projects", "Project")

    # Collapse SCL/CONTRACTOR duplicates into one row per project/month/year.
    # Prefer SCL when both exist; sum values when merging.
    grouped = {}
    for row in PlannedEarnedValue.objects.all().order_by("id"):
        key = (row.projectName.strip().lower(), row.month, row.year)
        grouped.setdefault(key, []).append(row)

    keep_ids = set()
    for rows in grouped.values():
        preferred = next((r for r in rows if r.value_type == "SCL"), rows[0])
        planned = sum((r.plannedValue or 0) for r in rows)
        actual = sum((r.earnedValue or 0) for r in rows)
        preferred.project_name = preferred.projectName.strip()
        preferred.planned_value = planned
        preferred.actual_value = actual
        preferred.collection = Decimal("0")
        preferred.difference = planned - actual
        preferred.achievement_percentage = (
            ((actual / planned) * Decimal("100")).quantize(Decimal("0.01"))
            if planned
            else Decimal("0")
        )
        preferred.collection_percentage = Decimal("0")
        preferred.variance_percentage = (
            ((preferred.difference / planned) * Decimal("100")).quantize(Decimal("0.01"))
            if planned
            else Decimal("0")
        )
        threshold = planned * Decimal("0.10")
        if preferred.difference == 0:
            preferred.variance_status = "ON_TRACK"
        elif preferred.difference <= threshold:
            preferred.variance_status = "MINOR_VARIANCE"
        else:
            preferred.variance_status = "MAJOR_VARIANCE"
        preferred.reason_for_difference = ""
        preferred.remarks = ""

        project = Project.objects.filter(name__iexact=preferred.project_name).first()
        preferred.project_id = project.id if project else None
        preferred.save()
        keep_ids.add(preferred.id)

        for row in rows:
            if row.id != preferred.id:
                row.delete()


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("projects", "0012_project_site_engineer"),
        ("planned_earned_value", "0003_alter_plannedearnedvalue_performancepercentage_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="plannedearnedvalue",
            name="project",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="planned_vs_actual_records",
                to="projects.project",
            ),
        ),
        migrations.AddField(
            model_name="plannedearnedvalue",
            name="project_name",
            field=models.CharField(blank=True, db_index=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="plannedearnedvalue",
            name="planned_value",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=20),
        ),
        migrations.AddField(
            model_name="plannedearnedvalue",
            name="actual_value",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=20),
        ),
        migrations.AddField(
            model_name="plannedearnedvalue",
            name="collection",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=20),
        ),
        migrations.AddField(
            model_name="plannedearnedvalue",
            name="difference",
            field=models.DecimalField(decimal_places=2, default=0, editable=False, max_digits=20),
        ),
        migrations.AddField(
            model_name="plannedearnedvalue",
            name="achievement_percentage",
            field=models.DecimalField(decimal_places=2, default=0, editable=False, max_digits=10),
        ),
        migrations.AddField(
            model_name="plannedearnedvalue",
            name="collection_percentage",
            field=models.DecimalField(decimal_places=2, default=0, editable=False, max_digits=10),
        ),
        migrations.AddField(
            model_name="plannedearnedvalue",
            name="variance_percentage",
            field=models.DecimalField(decimal_places=2, default=0, editable=False, max_digits=10),
        ),
        migrations.AddField(
            model_name="plannedearnedvalue",
            name="variance_status",
            field=models.CharField(
                choices=[
                    ("ON_TRACK", "On Track"),
                    ("MINOR_VARIANCE", "Minor Variance"),
                    ("MAJOR_VARIANCE", "Major Variance"),
                ],
                db_index=True,
                default="ON_TRACK",
                editable=False,
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="plannedearnedvalue",
            name="reason_for_difference",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="plannedearnedvalue",
            name="remarks",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="plannedearnedvalue",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="created_planned_vs_actual",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="plannedearnedvalue",
            name="updated_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="updated_planned_vs_actual",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(forwards_migrate, noop_reverse),
        migrations.AlterUniqueTogether(
            name="plannedearnedvalue",
            unique_together=set(),
        ),
        migrations.RemoveIndex(
            model_name="plannedearnedvalue",
            name="pev_proj_type_year_month_idx",
        ),
        migrations.RemoveField(model_name="plannedearnedvalue", name="projectName"),
        migrations.RemoveField(model_name="plannedearnedvalue", name="value_type"),
        migrations.RemoveField(model_name="plannedearnedvalue", name="plannedValue"),
        migrations.RemoveField(model_name="plannedearnedvalue", name="earnedValue"),
        migrations.RemoveField(model_name="plannedearnedvalue", name="variance"),
        migrations.RemoveField(model_name="plannedearnedvalue", name="variancePercentage"),
        migrations.RemoveField(model_name="plannedearnedvalue", name="performancePercentage"),
        migrations.AlterField(
            model_name="plannedearnedvalue",
            name="project_name",
            field=models.CharField(
                db_index=True,
                help_text="Denormalized project name for lookups and RBAC filters",
                max_length=255,
            ),
        ),
        migrations.AlterModelOptions(
            name="plannedearnedvalue",
            options={
                "ordering": ["project_name", "year", "month"],
                "verbose_name": "Planned vs Actual",
                "verbose_name_plural": "Planned vs Actual Records",
            },
        ),
        migrations.AddConstraint(
            model_name="plannedearnedvalue",
            constraint=models.UniqueConstraint(
                fields=("project_name", "month", "year"),
                name="pev_unique_project_month_year",
            ),
        ),
        migrations.AddIndex(
            model_name="plannedearnedvalue",
            index=models.Index(
                fields=["project_name", "year", "month"],
                name="pev_proj_year_month_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="plannedearnedvalue",
            index=models.Index(fields=["variance_status"], name="pev_variance_status_idx"),
        ),
    ]
