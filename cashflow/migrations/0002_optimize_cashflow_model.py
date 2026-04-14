# Migration to optimize CashFlow model: DecimalField + indexing
# Generated manually for performance and precision improvements

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cashflow', '0001_initial'),
    ]

    operations = [
        # Add composite index for better query performance
        migrations.AddIndex(
            model_name='cashflow',
            index=models.Index(fields=['project_name', 'month_year'], name='cashflow_project_month_idx'),
        ),

        # Add db_index to created_at for potential ordering queries
        migrations.AlterField(
            model_name='cashflow',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, db_index=True),
        ),

        # Convert FloatField to DecimalField for all financial fields
        # Monthly fields: 2 decimal places
        migrations.AlterField(
            model_name='cashflow',
            name='cash_in_monthly_plan',
            field=models.DecimalField(decimal_places=2, default=0, help_text='Monthly planned cash inflow', max_digits=14),
        ),
        migrations.AlterField(
            model_name='cashflow',
            name='cash_in_monthly_actual',
            field=models.DecimalField(decimal_places=2, default=0, help_text='Monthly actual cash inflow', max_digits=14),
        ),
        migrations.AlterField(
            model_name='cashflow',
            name='cash_out_monthly_plan',
            field=models.DecimalField(decimal_places=2, default=0, help_text='Monthly planned cash outflow', max_digits=14),
        ),
        migrations.AlterField(
            model_name='cashflow',
            name='cash_out_monthly_actual',
            field=models.DecimalField(decimal_places=2, default=0, help_text='Monthly actual cash outflow', max_digits=14),
        ),
        migrations.AlterField(
            model_name='cashflow',
            name='actual_cost_monthly',
            field=models.DecimalField(decimal_places=2, default=0, help_text='Monthly actual cost', max_digits=14),
        ),

        # Cumulative fields: 4 decimal places for calculation precision
        migrations.AlterField(
            model_name='cashflow',
            name='cash_in_cumulative_plan',
            field=models.DecimalField(decimal_places=4, default=0, help_text='Running total of planned cash inflow', max_digits=14),
        ),
        migrations.AlterField(
            model_name='cashflow',
            name='cash_in_cumulative_actual',
            field=models.DecimalField(decimal_places=4, default=0, help_text='Running total of actual cash inflow', max_digits=14),
        ),
        migrations.AlterField(
            model_name='cashflow',
            name='cash_out_cumulative_plan',
            field=models.DecimalField(decimal_places=4, default=0, help_text='Running total of planned cash outflow', max_digits=14),
        ),
        migrations.AlterField(
            model_name='cashflow',
            name='cash_out_cumulative_actual',
            field=models.DecimalField(decimal_places=4, default=0, help_text='Running total of actual cash outflow', max_digits=14),
        ),
        migrations.AlterField(
            model_name='cashflow',
            name='actual_cost_cumulative',
            field=models.DecimalField(decimal_places=4, default=0, help_text='Running total of actual cost', max_digits=14),
        ),
    ]