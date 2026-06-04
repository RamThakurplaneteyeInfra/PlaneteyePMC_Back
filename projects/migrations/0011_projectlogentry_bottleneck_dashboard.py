from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0010_projectlog_projectlogentry"),
    ]

    operations = [
        migrations.AlterField(
            model_name="projectlogentry",
            name="entry_type",
            field=models.CharField(
                choices=[
                    ("issue_concern", "Issue / Concern"),
                    ("risk_action", "Risk / Action"),
                    ("bottleneck_dashboard", "Bottleneck Dashboard"),
                ],
                db_index=True,
                max_length=32,
            ),
        ),
    ]
