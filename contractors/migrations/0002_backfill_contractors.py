"""Backfill Contractor Master from existing contractor_name values."""

from django.db import migrations


def _get_or_create_contractor(Contractor, project, name: str):
    name = (name or "").strip()
    if not name:
        return None
    contractor, _ = Contractor.objects.get_or_create(
        project=project,
        contractor_name=name,
        defaults={"status": "ACTIVE"},
    )
    return contractor


def backfill_contractors(apps, schema_editor):
    Contractor = apps.get_model("contractors", "Contractor")
    Project = apps.get_model("projects", "Project")
    ProjectDates = apps.get_model("project_dates", "ProjectDates")
    ContractValue = apps.get_model("contract_values", "ContractValue")
    InvoicingInformation = apps.get_model("invoicing", "InvoicingInformation")

    project_by_name = {p.name.lower(): p for p in Project.objects.all()}

    for row in ProjectDates.objects.filter(date_type="CONTRACTOR"):
        if row.contractor_id:
            continue
        project = row.project
        contractor = _get_or_create_contractor(Contractor, project, row.contractor_name)
        if contractor:
            row.contractor_id = contractor.id
            row.contractor_name = contractor.contractor_name
            row.save(update_fields=["contractor_id", "contractor_name"])

    for row in ContractValue.objects.filter(contract_type="CONTRACTOR"):
        if row.contractor_id:
            continue
        project = project_by_name.get((row.project_name or "").lower())
        if not project:
            continue
        contractor = _get_or_create_contractor(Contractor, project, row.contractor_name)
        if contractor:
            row.contractor_id = contractor.id
            row.contractor_name = contractor.contractor_name
            row.save(update_fields=["contractor_id", "contractor_name"])

    for row in InvoicingInformation.objects.filter(invoice_type="CONTRACTOR"):
        if row.contractor_id:
            continue
        project = project_by_name.get((row.project_name or "").lower())
        if not project:
            continue
        contractor = _get_or_create_contractor(Contractor, project, row.contractor_name)
        if contractor:
            row.contractor_id = contractor.id
            row.contractor_name = contractor.contractor_name
            row.save(update_fields=["contractor_id", "contractor_name"])


class Migration(migrations.Migration):

    dependencies = [
        ("contractors", "0001_initial"),
        ("project_dates", "0006_alter_projectbgstatus_options_and_more"),
        ("contract_values", "0007_contractvalue_contractor_and_more"),
        ("invoicing", "0008_remove_invoicinginformation_inv_unique_contractor_name_per_project_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_contractors, migrations.RunPython.noop),
    ]
