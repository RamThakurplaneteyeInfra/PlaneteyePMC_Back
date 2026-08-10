# Generated manually — add required section with backfill default for existing rows.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tutorial_videos", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="tutorialvideo",
            name="section",
            field=models.CharField(
                choices=[
                    ("overview", "Overview"),
                    ("projects", "Projects"),
                    ("initialize_project", "Initialize Project"),
                    ("user_management", "User Management"),
                    ("site_progress", "Site Progress"),
                    ("site_photos", "Site Photos"),
                    ("testing_photos", "Testing Photos"),
                    ("project_feedback", "Project Feedback"),
                    ("portfolio", "Portfolio"),
                    ("dpr_review", "DPR Review"),
                    ("wpr_review", "WPR Review"),
                    ("meeting_documents", "Meeting Documents"),
                    ("alerts", "Alerts"),
                ],
                db_index=True,
                default="overview",
                help_text="Stable sidebar section key (e.g. meeting_documents)",
                max_length=64,
            ),
            preserve_default=False,
        ),
        migrations.AddIndex(
            model_name="tutorialvideo",
            index=models.Index(
                fields=["section", "is_active", "-created_at"],
                name="tutorial_section_active_idx",
            ),
        ),
    ]
