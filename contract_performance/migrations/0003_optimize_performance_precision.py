# Migration to optimize ContractPerformance model: DecimalField + indexing
# Generated manually for performance and precision improvements

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('contract_performance', '0002_alter_contractperformance_variance_and_more'),
    ]

    operations = [
        # Convert percentage fields from FloatField to DecimalField for precision
        migrations.AlterField(
            model_name='contractperformance',
            name='earned_value_percentage',
            field=models.DecimalField(
                decimal_places=4, default=0,
                help_text='Earned Value percentage (calculated: earned_value / contract_value * 100)',
                max_digits=10
            ),
        ),
        migrations.AlterField(
            model_name='contractperformance',
            name='actual_billed_percentage',
            field=models.DecimalField(
                decimal_places=4, default=0,
                help_text='Actual Billed percentage (calculated: actual_billed / contract_value * 100)',
                max_digits=10
            ),
        ),
        migrations.AlterField(
            model_name='contractperformance',
            name='variance_percentage',
            field=models.DecimalField(
                decimal_places=4, default=0,
                help_text='Variance percentage (calculated: variance / contract_value * 100). Can be negative if actual_billed > earned_value.',
                max_digits=10
            ),
        ),

        # Add db_index to project_name for better query performance
        migrations.AlterField(
            model_name='contractperformance',
            name='project_name',
            field=models.CharField(
                db_index=True,
                help_text='Project name for this performance record',
                max_length=255
            ),
        ),

        # Add db_index to created_at for time-based queries
        migrations.AlterField(
            model_name='contractperformance',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, db_index=True),
        ),
    ]