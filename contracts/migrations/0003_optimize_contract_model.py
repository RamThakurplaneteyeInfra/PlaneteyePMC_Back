# Migration to optimize Contract model: indexing + DecimalField + validation
# Generated manually for performance and precision improvements

from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ('contracts', '0002_alter_contract_approved_vo_percentage'),
    ]

    operations = [
        # Add db_index to project_name for faster queries
        migrations.AlterField(
            model_name='contract',
            name='project_name',
            field=models.CharField(db_index=True, max_length=255),
        ),

        # Add db_index to created_at for time-based queries
        migrations.AlterField(
            model_name='contract',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, db_index=True),
        ),

        # Add MinValueValidator to original_contract_value
        migrations.AlterField(
            model_name='contract',
            name='original_contract_value',
            field=models.DecimalField(
                decimal_places=2,
                max_digits=18,
                validators=[django.core.validators.MinValueValidator(0)]
            ),
        ),

        # Convert approved_vo_percentage from FloatField to DecimalField for precision
        migrations.AlterField(
            model_name='contract',
            name='approved_vo_percentage',
            field=models.DecimalField(
                decimal_places=4,
                default=0,
                max_digits=10,
                validators=[django.core.validators.MinValueValidator(0)]
            ),
        ),
    ]