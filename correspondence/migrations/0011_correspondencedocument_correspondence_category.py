from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("correspondence", "0010_scldeliveredcorrespondencesummary_client_record_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="correspondencedocument",
            name="correspondence_category",
            field=models.CharField(
                choices=[("DELIVERY", "Delivery"), ("RECORD", "Record")],
                db_index=True,
                default="DELIVERY",
                help_text="DELIVERY = normal delivery tracking; RECORD = filed as record",
                max_length=20,
            ),
        ),
    ]
