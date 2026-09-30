from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("organization_registrations", "0002_logo_optional_for_s3"),
    ]

    operations = [
        migrations.AddField(
            model_name="organizationregistration",
            name="notification_status",
            field=models.CharField(
                choices=[("pending", "Pending"), ("sent", "Sent"), ("failed", "Failed")],
                db_index=True,
                default="pending",
                max_length=20,
            ),
        ),
    ]