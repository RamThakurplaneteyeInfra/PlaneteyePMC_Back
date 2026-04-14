# Migration to optimize ProjectCostPerformance model: DecimalField + indexing
# Generated manually for performance and precision improvements

from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ('cost_performance', '0003_populate_project_field'),
    ]

    operations = [
        # Add db_index to created_at for time-based queries
        migrations.AlterField(
            model_name='projectcostperformance',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, db_index=True),
        ),

        # Convert all financial fields from FloatField to DecimalField for precision
        migrations.AlterField(
            model_name='projectcostperformance',
            name='bcws',
            field=models.DecimalField(decimal_places=4, help_text='Budgeted Cost of Work Scheduled (planned cost)', max_digits=18),
        ),
        migrations.AlterField(
            model_name='projectcostperformance',
            name='bcwp',
            field=models.DecimalField(decimal_places=4, help_text='Budgeted Cost of Work Performed (earned value)', max_digits=18),
        ),
        migrations.AlterField(
            model_name='projectcostperformance',
            name='acwp',
            field=models.DecimalField(decimal_places=4, help_text='Actual Cost of Work Performed', max_digits=18),
        ),
        migrations.AlterField(
            model_name='projectcostperformance',
            name='fcst',
            field=models.DecimalField(decimal_places=4, help_text='Forecast cost of remaining work', max_digits=18),
        ),
        migrations.AlterField(
            model_name='projectcostperformance',
            name='eac',
            field=models.DecimalField(decimal_places=4, default=0, help_text='EAC = ACWP + FCST', max_digits=18),
        ),
        migrations.AlterField(
            model_name='projectcostperformance',
            name='cv',
            field=models.DecimalField(decimal_places=4, default=0, help_text='CV = BCWP - ACWP', max_digits=18),
        ),
        migrations.AlterField(
            model_name='projectcostperformance',
            name='sv',
            field=models.DecimalField(decimal_places=4, default=0, help_text='SV = BCWP - BCWS', max_digits=18),
        ),

        # Optional fields with higher precision where needed
        migrations.AlterField(
            model_name='projectcostperformance',
            name='bac',
            field=models.DecimalField(blank=True, decimal_places=4, help_text='Budget at completion (optional; used for VAC)', max_digits=18, null=True),
        ),
        migrations.AlterField(
            model_name='projectcostperformance',
            name='cpi',
            field=models.DecimalField(blank=True, decimal_places=6, help_text='CPI = BCWP/ACWP', max_digits=10, null=True),
        ),
        migrations.AlterField(
            model_name='projectcostperformance',
            name='vac',
            field=models.DecimalField(blank=True, decimal_places=4, help_text='VAC = BAC - EAC when BAC set', max_digits=18, null=True),
        ),

        # Add composite index for better query performance
        migrations.AddIndex(
            model_name='projectcostperformance',
            index=models.Index(fields=['project', 'month_year'], name='costperf_project_month_idx'),
        ),
    ]