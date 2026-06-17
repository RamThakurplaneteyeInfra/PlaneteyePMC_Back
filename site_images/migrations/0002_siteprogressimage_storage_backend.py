from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("site_images", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="siteprogressimage",
            name="storage_backend",
            field=models.CharField(
                choices=[("s3", "AWS S3"), ("cloudinary", "Cloudinary")],
                db_index=True,
                default="cloudinary",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="siteprogressimage",
            name="cloudinary_public_id",
            field=models.CharField(
                help_text="Storage key (S3 object key or Cloudinary public_id)",
                max_length=500,
                unique=True,
            ),
        ),
    ]
