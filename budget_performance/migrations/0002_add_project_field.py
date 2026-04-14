# Generated manually for adding project ForeignKey

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('budget_performance', '0001_initial'),
        ('projects', '0001_initial'),  # Ensure projects app exists
    ]

    operations = [
        migrations.AddField(
            model_name='budgetcostperformance',
            name='project',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='budget_performances',
                to='projects.project'
            ),
        ),
    ]