from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("accounts", "0002_notification"),
    ]

    operations = [
        migrations.AddField(
            model_name="notification",
            name="action_type",
            field=models.CharField(
                blank=True,
                choices=[("CREATE", "Create"), ("UPDATE", "Update"), ("DELETE", "Delete")],
                default="",
                help_text="Create, update, or delete action",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="notification",
            name="module_name",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Financial module that was updated",
                max_length=120,
            ),
        ),
        migrations.AddField(
            model_name="notification",
            name="project",
            field=models.ForeignKey(
                blank=True,
                help_text="Project related to the notification",
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="notifications",
                to="projects.project",
            ),
        ),
        migrations.AddField(
            model_name="notification",
            name="sender",
            field=models.ForeignKey(
                blank=True,
                help_text="User who triggered the notification",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="sent_notifications",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="notification",
            name="title",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Short notification title",
                max_length=255,
            ),
        ),
        migrations.AlterField(
            model_name="notification",
            name="notification_type",
            field=models.CharField(
                choices=[
                    ("project_assigned", "Project Assigned"),
                    ("dpr_submitted", "DPR Submitted"),
                    ("dpr_approved", "DPR Approved"),
                    ("dpr_rejected", "DPR Rejected"),
                    ("BILLING_UPDATE", "Billing Data Updated"),
                ],
                help_text="Type of notification",
                max_length=30,
            ),
        ),
    ]
