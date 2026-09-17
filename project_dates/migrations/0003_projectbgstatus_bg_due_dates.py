# Generated manually for BG due/updated date fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("project_dates", "0002_projectbgstatus"),
    ]

    operations = [
        migrations.RenameField(
            model_name="projectbgstatus",
            old_name="contractor_bg_date",
            new_name="contractor_bg_updated_date",
        ),
        migrations.RenameField(
            model_name="projectbgstatus",
            old_name="scl_bg_date",
            new_name="scl_bg_updated_date",
        ),
        migrations.AlterField(
            model_name="projectbgstatus",
            name="contractor_bg_updated_date",
            field=models.DateField(
                blank=True,
                help_text="Contractor bank guarantee updated date",
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="projectbgstatus",
            name="scl_bg_updated_date",
            field=models.DateField(
                blank=True,
                help_text="SCL bank guarantee updated date",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="projectbgstatus",
            name="contractor_bg_due_date",
            field=models.DateField(
                blank=True,
                help_text="Contractor bank guarantee due date for the current monthly milestone",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="projectbgstatus",
            name="scl_bg_due_date",
            field=models.DateField(
                blank=True,
                help_text="SCL bank guarantee due date for the current monthly milestone",
                null=True,
            ),
        ),
    ]
