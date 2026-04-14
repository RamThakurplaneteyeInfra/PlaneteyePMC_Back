# Generated manually for data migration

from django.db import migrations
from projects.models import Project


def populate_project_field(apps, schema_editor):
    """
    Populate the new 'project' ForeignKey field based on existing 'project_name' values.
    Create Project objects for any missing project names.
    """
    BudgetCostPerformance = apps.get_model('budget_performance', 'BudgetCostPerformance')
    Project = apps.get_model('projects', 'Project')

    # Get all unique project names from existing records
    unique_project_names = BudgetCostPerformance.objects.values_list(
        'project_name', flat=True
    ).distinct()

    # Create a mapping of project_name to Project object
    project_map = {}
    for project_name in unique_project_names:
        project_name = project_name.strip()
        if not project_name:
            continue

        # Try to find existing project
        project = Project.objects.filter(name=project_name).first()

        if not project:
            # Create a new project with minimal required fields
            project = Project.objects.create(
                name=project_name,
                # Set other required fields with defaults if needed
                budget=0,
            )

        project_map[project_name] = project

    # Update all records with the project field
    for record in BudgetCostPerformance.objects.filter(project__isnull=True):
        project_name = record.project_name.strip()
        if project_name in project_map:
            record.project = project_map[project_name]
            record.save(update_fields=['project'])


def reverse_populate_project_field(apps, schema_editor):
    """
    Reverse migration: populate project_name from project field.
    """
    BudgetCostPerformance = apps.get_model('budget_performance', 'BudgetCostPerformance')

    for record in BudgetCostPerformance.objects.filter(project__isnull=False):
        record.project_name = record.project.name
        record.save(update_fields=['project_name'])


class Migration(migrations.Migration):

    dependencies = [
        ('budget_performance', '0002_add_project_field'),
        ('projects', '0001_initial'),  # Ensure projects app migration exists
    ]

    operations = [
        migrations.RunPython(
            populate_project_field,
            reverse_code=reverse_populate_project_field
        ),
    ]