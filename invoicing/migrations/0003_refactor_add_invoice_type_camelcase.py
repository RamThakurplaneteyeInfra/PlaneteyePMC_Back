"""
Migration: Refactor InvoicingInformation to support multiple invoice types.

Changes:
  1. Rename snake_case fields to camelCase (matching new model definition)
  2. Add invoiceType field (enum: PMC | Contractor)
  3. Add new camelCase financial fields
  4. Remove old snake_case fields (gross_billed, net_billed_without_vat,
     net_collected, net_due, created_by, updated_by)
  5. Add unique constraint on (projectName, invoiceType)
  6. Add new indexes

Strategy:
  - Existing rows get invoiceType = "PMC" as the one-off default
    (safe: existing data was PMC invoicing)
  - Old created_by / updated_by tracking fields are dropped
    (new module uses AllowAny, no role-based tracking)
"""

import django.utils.timezone
from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("invoicing", "0002_alter_invoicinginformation_created_at_and_more"),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name="invoicinginformation",
            name="invoicing_i_project_b594ae_idx",
        ),
        migrations.RemoveIndex(
            model_name="invoicinginformation",
            name="invoicing_i_project_7c5626_idx",
        ),

        # ── Step 1: Rename project_name → projectName ─────────────────────
        migrations.RenameField(
            model_name="invoicinginformation",
            old_name="project_name",
            new_name="projectName",
        ),

        # ── Step 2: Add invoiceType with a default so existing rows are valid
        migrations.AddField(
            model_name="invoicinginformation",
            name="invoiceType",
            field=models.CharField(
                choices=[("PMC", "PMC"), ("Contractor", "Contractor")],
                db_index=True,
                default="PMC",          # existing rows → PMC
                help_text='Invoice type: "PMC" or "Contractor"',
                max_length=50,
            ),
            preserve_default=False,     # remove default after migration
        ),

        # ── Step 3: Add new camelCase financial fields ─────────────────────
        migrations.AddField(
            model_name="invoicinginformation",
            name="grossBilled",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                help_text="Total amount billed including VAT (>= 0)",
                max_digits=20,
            ),
        ),
        migrations.AddField(
            model_name="invoicinginformation",
            name="netBilledWithoutVAT",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                help_text="Net amount billed excluding VAT (>= 0)",
                max_digits=20,
            ),
        ),
        migrations.AddField(
            model_name="invoicinginformation",
            name="netCollected",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                help_text="Amount actually collected (>= 0)",
                max_digits=20,
            ),
        ),
        migrations.AddField(
            model_name="invoicinginformation",
            name="netDue",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                editable=False,
                help_text="Auto-calculated: netBilledWithoutVAT - netCollected",
                max_digits=20,
            ),
        ),

        # ── Step 4: Copy data from old fields to new camelCase fields ──────
        migrations.RunSQL(
            sql="""
                UPDATE invoicing_invoicinginformation
                SET
                    "grossBilled"        = gross_billed,
                    "netBilledWithoutVAT" = net_billed_without_vat,
                    "netCollected"       = net_collected,
                    "netDue"             = net_due
            """,
            reverse_sql="""
                UPDATE invoicing_invoicinginformation
                SET
                    gross_billed           = "grossBilled",
                    net_billed_without_vat = "netBilledWithoutVAT",
                    net_collected          = "netCollected",
                    net_due                = "netDue"
            """,
        ),

        # ── Step 5: Remove old snake_case financial fields ─────────────────
        migrations.RemoveField(
            model_name="invoicinginformation",
            name="gross_billed",
        ),
        migrations.RemoveField(
            model_name="invoicinginformation",
            name="net_billed_without_vat",
        ),
        migrations.RemoveField(
            model_name="invoicinginformation",
            name="net_collected",
        ),
        migrations.RemoveField(
            model_name="invoicinginformation",
            name="net_due",
        ),

        # ── Step 6: Remove old tracking fields (no longer needed) ──────────
        migrations.RemoveField(
            model_name="invoicinginformation",
            name="created_by",
        ),
        migrations.RemoveField(
            model_name="invoicinginformation",
            name="updated_by",
        ),

        # ── Step 7: Update created_at to use default=timezone.now ──────────
        migrations.AlterField(
            model_name="invoicinginformation",
            name="created_at",
            field=models.DateTimeField(
                db_index=True,
                default=django.utils.timezone.now,
                editable=False,
                help_text="Record creation timestamp",
            ),
        ),

        # ── Step 8: Deduplicate rows before adding unique constraint ──────
        # Existing data may have multiple rows per project (all defaulted to PMC).
        # Keep only the latest row per (projectName, invoiceType) pair.
        migrations.RunSQL(
            sql="""
                DELETE FROM invoicing_invoicinginformation
                WHERE id NOT IN (
                    SELECT MAX(id)
                    FROM invoicing_invoicinginformation
                    GROUP BY "projectName", "invoiceType"
                )
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),

        # ── Step 9: Add unique constraint on (projectName, invoiceType) ────
        migrations.AddConstraint(
            model_name="invoicinginformation",
            constraint=models.UniqueConstraint(
                fields=["projectName", "invoiceType"],
                name="inv_unique_project_invoice_type",
            ),
        ),

        # ── Step 9: Add new indexes ─────────────────────────────────────────
        migrations.AddIndex(
            model_name="invoicinginformation",
            index=models.Index(
                fields=["projectName"],
                name="inv_project_name_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="invoicinginformation",
            index=models.Index(
                fields=["invoiceType"],
                name="inv_invoice_type_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="invoicinginformation",
            index=models.Index(
                fields=["projectName", "invoiceType"],
                name="inv_project_type_idx",
            ),
        ),

        # ── Step 10: Update Meta ordering ──────────────────────────────────
        migrations.AlterModelOptions(
            name="invoicinginformation",
            options={
                "ordering": ["projectName", "invoiceType"],
                "verbose_name": "Invoicing Information",
                "verbose_name_plural": "Invoicing Information",
            },
        ),
    ]
