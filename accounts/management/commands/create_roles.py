"""
Django management command to create user roles (groups)
Run: python manage.py create_roles
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType


class Command(BaseCommand):
    help = 'Creates all user role groups for the PMC system'

    def handle(self, *args, **options):
        # Define all roles
        roles = [
            {
                'name': 'PMC Head',
                'description': 'PMC Head - Full system access and project oversight'
            },
            {
                'name': 'CEO',
                'description': 'CEO - Executive level access to all projects and reports'
            },
            {
                'name': 'Coordinator',
                'description': 'Coordinator - Manages project coordination and communication'
            },
            {
                'name': 'Team Leader',
                'description': 'Team Leader - Leads project teams and manages project execution'
            },
            {
                'name': 'Site Engineer',
                'description': 'Site Engineer - General site engineering and project execution'
            },
            {
                'name': 'Billing Site Engineer',
                'description': 'Billing Site Engineer - Handles billing, invoicing, and financial aspects'
            },
            {
                'name': 'QAQC Site Engineer',
                'description': 'QAQC Site Engineer - Quality Assurance and Quality Control'
            },
        ]

        created_count = 0
        existing_count = 0

        for role in roles:
            group, created = Group.objects.get_or_create(name=role['name'])
            
            if created:
                self.stdout.write(
                    self.style.SUCCESS(f'[OK] Created role: {role["name"]}')
                )
                created_count += 1
            else:
                self.stdout.write(
                    self.style.WARNING(f'[EXISTS] Role already exists: {role["name"]}')
                )
                existing_count += 1

        self.stdout.write('\n' + '='*60)
        self.stdout.write(self.style.SUCCESS(
            f'Role creation complete!\n'
            f'Created: {created_count} roles\n'
            f'Already existed: {existing_count} roles\n'
            f'Total roles: {created_count + existing_count}'
        ))
        self.stdout.write('='*60)
        
        # List all roles
        self.stdout.write('\nAll available roles:')
        for group in Group.objects.all().order_by('name'):
            self.stdout.write(f'  - {group.name}')
