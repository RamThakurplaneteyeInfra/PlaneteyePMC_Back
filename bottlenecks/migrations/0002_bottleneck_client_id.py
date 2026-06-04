from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bottlenecks", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="bottleneck",
            name="client_id",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="Frontend UUID for dashboard sync via project-logs",
                max_length=64,
                null=True,
            ),
        ),
        migrations.AddConstraint(
            model_name="bottleneck",
            constraint=models.UniqueConstraint(
                condition=models.Q(("client_id__isnull", False)),
                fields=("project", "client_id"),
                name="unique_bottleneck_client_id_per_project",
            ),
        ),
    ]
