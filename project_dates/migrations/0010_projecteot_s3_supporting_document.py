# Generated manually — EOT supporting docs move from local FileField to S3 (eot/ prefix).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("project_dates", "0009_migrate_legacy_eot_dates"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="projecteot",
            name="supporting_document",
        ),
        migrations.AddField(
            model_name="projecteot",
            name="supporting_document_key",
            field=models.CharField(
                blank=True,
                db_index=True,
                default="",
                help_text="S3 object key under eot/… (empty if no document)",
                max_length=512,
            ),
        ),
        migrations.AddField(
            model_name="projecteot",
            name="supporting_document_name",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Original uploaded filename",
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name="projecteot",
            name="supporting_document_url",
            field=models.URLField(
                blank=True,
                default="",
                help_text="Public HTTPS URL for the supporting document on S3",
                max_length=1024,
            ),
        ),
    ]
