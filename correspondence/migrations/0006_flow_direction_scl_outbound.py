from django.db import migrations, models


def set_inbound_defaults(apps, schema_editor):
    CorrespondenceDocument = apps.get_model("correspondence", "CorrespondenceDocument")
    CorrespondenceDocument.objects.all().update(
        flow_direction="INBOUND",
    )
    for doc in CorrespondenceDocument.objects.all().iterator():
        doc.sender = doc.correspondence_type
        doc.save(update_fields=["sender"])


class Migration(migrations.Migration):

    dependencies = [
        ("correspondence", "0005_rename_delivery_to_delivered"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="correspondencedocument",
            name="corr_doc_unique_project_period_type_sr",
        ),
        migrations.AddField(
            model_name="correspondencedocument",
            name="flow_direction",
            field=models.CharField(
                choices=[
                    ("INBOUND", "Inbound"),
                    ("OUTBOUND_SCL", "SCL Outbound"),
                ],
                db_index=True,
                default="INBOUND",
                help_text="INBOUND = received tracking; OUTBOUND_SCL = sent by SCL",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="correspondencedocument",
            name="recipient_type",
            field=models.CharField(
                blank=True,
                choices=[
                    ("CLIENT", "Client"),
                    ("CONTRACTOR", "Contractor"),
                    ("OTHER_AGENCY", "Other Agency"),
                ],
                db_index=True,
                help_text="Recipient for SCL outbound documents",
                max_length=20,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="correspondencedocument",
            name="sender",
            field=models.CharField(
                choices=[
                    ("SCL", "SCL"),
                    ("CLIENT", "Client"),
                    ("CONTRACTOR", "Contractor"),
                ],
                db_index=True,
                default="CLIENT",
                help_text="Document sender (SCL for outbound correspondence)",
                max_length=20,
            ),
        ),
        migrations.RunPython(set_inbound_defaults, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="correspondencedocument",
            name="correspondence_type",
            field=models.CharField(
                choices=[
                    ("CLIENT", "CLIENT"),
                    ("CONTRACTOR", "CONTRACTOR"),
                    ("OTHER_AGENCY", "OTHER_AGENCY"),
                ],
                db_index=True,
                help_text="CLIENT, CONTRACTOR, or OTHER_AGENCY",
                max_length=20,
            ),
        ),
        migrations.AddConstraint(
            model_name="correspondencedocument",
            constraint=models.UniqueConstraint(
                fields=[
                    "project_name",
                    "month",
                    "year",
                    "correspondence_type",
                    "flow_direction",
                    "sr_no",
                ],
                name="corr_doc_unique_project_period_flow_sr",
            ),
        ),
    ]
