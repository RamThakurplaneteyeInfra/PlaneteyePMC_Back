"""Add contractor_name and support multiple contractor contract values per project."""

from django.db import migrations, models
from django.db.models import Q


def backfill_contractor_names(apps, schema_editor):
    ContractValue = apps.get_model("contract_values", "ContractValue")
    for row in ContractValue.objects.filter(contract_type="CONTRACTOR"):
        if not (row.contractor_name or "").strip():
            row.contractor_name = "Contractor"
            row.save(update_fields=["contractor_name"])


class Migration(migrations.Migration):

    dependencies = [
        ("contract_values", "0003_remove_contractvalue_cv_project_name_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="contractvalue",
            name="contractor_name",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="Contractor display name (required for CONTRACTOR; null for SCL)",
                max_length=255,
                null=True,
            ),
        ),
        migrations.RunPython(backfill_contractor_names, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name="contractvalue",
            name="cv_unique_project_contract_type",
        ),
        migrations.AddConstraint(
            model_name="contractvalue",
            constraint=models.UniqueConstraint(
                fields=("project_name", "contract_type"),
                condition=Q(contract_type="SCL"),
                name="cv_unique_scl_per_project",
            ),
        ),
        migrations.AddConstraint(
            model_name="contractvalue",
            constraint=models.UniqueConstraint(
                fields=("project_name", "contractor_name"),
                condition=Q(contract_type="CONTRACTOR"),
                name="cv_unique_contractor_name_per_project",
            ),
        ),
        migrations.AddIndex(
            model_name="contractvalue",
            index=models.Index(
                fields=["project_name", "contractor_name"],
                name="cv_project_contractor_idx",
            ),
        ),
    ]
