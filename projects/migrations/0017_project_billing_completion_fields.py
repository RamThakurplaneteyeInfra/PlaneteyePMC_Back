# Generated manually for billing completion fields

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0016_project_completion_fields"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="billing_status",
            field=models.CharField(
                choices=[("Pending", "Pending"), ("Completed", "Completed")],
                db_index=True,
                default="Pending",
                help_text="Commercial/billing closure status (Pending or Completed)",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="project",
            name="billing_completed_at",
            field=models.DateTimeField(
                blank=True,
                db_index=True,
                help_text="When billing was marked completed",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="project",
            name="billing_completed_by",
            field=models.ForeignKey(
                blank=True,
                help_text="User who marked billing as completed",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="billing_completed_projects",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="project",
            name="billing_completion_notes",
            field=models.TextField(
                blank=True,
                help_text="Optional remarks captured at billing completion",
                null=True,
            ),
        ),
        migrations.AddIndex(
            model_name="project",
            index=models.Index(
                fields=["status", "billing_status"],
                name="project_status_billing_idx",
            ),
        ),
    ]
