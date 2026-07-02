"""Add contractor_name and support multiple contractor invoicing records per project."""

from django.db import migrations, models
from django.db.models import Q


def backfill_contractor_names(apps, schema_editor):
    InvoicingInformation = apps.get_model("invoicing", "InvoicingInformation")
    for row in InvoicingInformation.objects.filter(invoice_type="CONTRACTOR"):
        if not (row.contractor_name or "").strip():
            row.contractor_name = "Contractor"
            row.save(update_fields=["contractor_name"])


class Migration(migrations.Migration):

    dependencies = [
        ("invoicing", "0005_remove_invoicinginformation_invoicing_i_project_b594ae_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="invoicinginformation",
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
            model_name="invoicinginformation",
            name="inv_unique_project_invoice_type",
        ),
        migrations.AddConstraint(
            model_name="invoicinginformation",
            constraint=models.UniqueConstraint(
                fields=("project_name", "invoice_type"),
                condition=Q(invoice_type="SCL"),
                name="inv_unique_scl_per_project",
            ),
        ),
        migrations.AddConstraint(
            model_name="invoicinginformation",
            constraint=models.UniqueConstraint(
                fields=("project_name", "contractor_name"),
                condition=Q(invoice_type="CONTRACTOR"),
                name="inv_unique_contractor_name_per_project",
            ),
        ),
        migrations.AddIndex(
            model_name="invoicinginformation",
            index=models.Index(
                fields=["project_name", "contractor_name"],
                name="inv_project_contractor_idx",
            ),
        ),
    ]
