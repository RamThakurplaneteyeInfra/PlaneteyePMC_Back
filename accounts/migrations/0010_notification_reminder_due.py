# Generated manually for REMINDER_DUE notification type

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0009_project_completion_fields"),
    ]

    operations = [
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
                    ("MEETING_DOCUMENT", "Meeting Document Uploaded"),
                    ("CORRESPONDENCE_ATTACHMENT", "Correspondence Document Uploaded"),
                    ("project_completed", "Project Completed"),
                    ("REMINDER_DUE", "Reminder Due"),
                ],
                help_text="Type of notification",
                max_length=30,
            ),
        ),
    ]
