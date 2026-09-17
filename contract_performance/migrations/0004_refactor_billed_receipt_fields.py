"""
Migration: Refactor ContractPerformance to use billedValue / actualReceiptValue.

Changes from old schema → new schema:

  Renamed fields:
    project_name            → projectName
    earned_value            → billedValue
    actual_billed           → actualReceiptValue
    variance_percentage     → variancePercentage
    earned_value_percentage → (repurposed as variancePercentage — see below)

  New calculated fields added:
    variancePercentage      (was variance_percentage, formula updated)
    performancePercentage   (new — was earned_value_percentage with different formula)

  Removed fields (no longer in spec):
    contract_value
    earned_value_percentage   (replaced by variancePercentage + performancePercentage)
    actual_billed_percentage  (removed)
    performance_status        (removed)
    created_by                (removed)
    updated_by                (removed)

  Schema changes:
    - projectName gets unique=True constraint
    - New index: cp_project_name_idx
    - created_at changes from auto_now_add to default=timezone.now
    - ordering changes from ["-created_at"] to ["projectName"]

Data migration strategy:
  - Existing rows: billedValue ← earned_value, actualReceiptValue ← actual_billed
  - variance stays (same column, same formula direction)
  - variancePercentage and performancePercentage are recalculated from new values
  - Duplicate projectName rows: keep only the latest per project before
    applying the unique constraint
"""

import django.utils.timezone
from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("contract_performance", "0003_optimize_performance_precision"),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name="contractperformance",
            name="contract_pe_project_bb13ca_idx",
        ),
        migrations.RemoveIndex(
            model_name="contractperformance",
            name="contract_pe_perform_cd5942_idx",
        ),

        # ── Step 1: Rename project_name → projectName ─────────────────────
        migrations.RenameField(
            model_name="contractperformance",
            old_name="project_name",
            new_name="projectName",
        ),

        # ── Step 2: Rename earned_value → billedValue ─────────────────────
        migrations.RenameField(
            model_name="contractperformance",
            old_name="earned_value",
            new_name="billedValue",
        ),

        # ── Step 3: Rename actual_billed → actualReceiptValue ─────────────
        migrations.RenameField(
            model_name="contractperformance",
            old_name="actual_billed",
            new_name="actualReceiptValue",
        ),

        # ── Step 4: Add new camelCase calculated fields ────────────────────
        migrations.AddField(
            model_name="contractperformance",
            name="variancePercentage",
            field=models.FloatField(
                default=0.0,
                editable=False,
                help_text="Auto-calculated: (variance / billedValue) * 100. 0.0 when billedValue = 0.",
            ),
        ),
        migrations.AddField(
            model_name="contractperformance",
            name="performancePercentage",
            field=models.FloatField(
                default=0.0,
                editable=False,
                help_text="Auto-calculated: (actualReceiptValue / billedValue) * 100. 0.0 when billedValue = 0.",
            ),
        ),

        # ── Step 5: Alter billedValue field spec (widen, remove validator) ─
        migrations.AlterField(
            model_name="contractperformance",
            name="billedValue",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                help_text="Total billed value (>= 0)",
                max_digits=20,
            ),
        ),

        # ── Step 6: Alter actualReceiptValue field spec ────────────────────
        migrations.AlterField(
            model_name="contractperformance",
            name="actualReceiptValue",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                help_text="Actual receipt / collection value (>= 0)",
                max_digits=20,
            ),
        ),

        # ── Step 7: Alter variance field spec (widen, editable=False) ──────
        migrations.AlterField(
            model_name="contractperformance",
            name="variance",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                editable=False,
                help_text="Auto-calculated: billedValue - actualReceiptValue.",
                max_digits=20,
            ),
        ),

        # ── Step 8: Populate new percentage fields from existing data ──────
        migrations.RunSQL(
            sql="""
                UPDATE contract_performance_contractperformance
                SET
                    "variancePercentage" = CASE
                        WHEN "billedValue" > 0
                        THEN ROUND(CAST(variance / "billedValue" * 100 AS NUMERIC), 2)
                        ELSE 0.0
                    END,
                    "performancePercentage" = CASE
                        WHEN "billedValue" > 0
                        THEN ROUND(CAST("actualReceiptValue" / "billedValue" * 100 AS NUMERIC), 2)
                        ELSE 0.0
                    END
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),

        # ── Step 9: Remove old fields no longer in spec ────────────────────
        migrations.RemoveField(
            model_name="contractperformance",
            name="contract_value",
        ),
        migrations.RemoveField(
            model_name="contractperformance",
            name="earned_value_percentage",
        ),
        migrations.RemoveField(
            model_name="contractperformance",
            name="actual_billed_percentage",
        ),
        migrations.RemoveField(
            model_name="contractperformance",
            name="variance_percentage",
        ),
        migrations.RemoveField(
            model_name="contractperformance",
            name="performance_status",
        ),
        migrations.RemoveField(
            model_name="contractperformance",
            name="created_by",
        ),
        migrations.RemoveField(
            model_name="contractperformance",
            name="updated_by",
        ),

        # ── Step 10: Update created_at to use default=timezone.now ─────────
        migrations.AlterField(
            model_name="contractperformance",
            name="created_at",
            field=models.DateTimeField(
                db_index=True,
                default=django.utils.timezone.now,
                editable=False,
                help_text="Record creation timestamp",
            ),
        ),

        # ── Step 11: Deduplicate rows before adding unique constraint ───────
        # Existing data may have multiple rows per project.
        # Keep only the latest row per projectName.
        migrations.RunSQL(
            sql="""
                DELETE FROM contract_performance_contractperformance
                WHERE id NOT IN (
                    SELECT MAX(id)
                    FROM contract_performance_contractperformance
                    GROUP BY "projectName"
                )
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),

        # ── Step 12: Add unique constraint on projectName ──────────────────
        migrations.AlterField(
            model_name="contractperformance",
            name="projectName",
            field=models.CharField(
                db_index=True,
                help_text="Unique project name for this contract performance record",
                max_length=255,
                unique=True,
            ),
        ),

        # ── Step 13: Add new index ──────────────────────────────────────────
        migrations.AddIndex(
            model_name="contractperformance",
            index=models.Index(
                fields=["projectName"],
                name="cp_project_name_idx",
            ),
        ),

        # ── Step 14: Update Meta ordering ──────────────────────────────────
        migrations.AlterModelOptions(
            name="contractperformance",
            options={
                "ordering": ["projectName"],
                "verbose_name": "Contract Performance",
                "verbose_name_plural": "Contract Performance Records",
            },
        ),
    ]
