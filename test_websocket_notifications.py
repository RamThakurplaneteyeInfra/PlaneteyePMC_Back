#!/usr/bin/env python
"""
Test script to verify WebSocket notifications are working
"""
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()

from services.notifications import notify_project_created, notify_project_assigned, notify_dpr_submitted
from projects.models import Project
from django.contrib.auth.models import User

def test_notifications():
    print("Testing WebSocket notifications...")

    # Get a test project
    try:
        project = Project.objects.filter(coordinators__isnull=False).first()
        if not project:
            print("No projects with coordinators found")
            return

        print(f"Testing with project: {project.name}")

        # Test project created notification
        print("Sending project created notification...")
        notify_project_created(project)

        # Test project assigned notification
        user = project.coordinators.first()
        if user:
            print(f"Sending project assigned notification to {user.username}...")
            notify_project_assigned(project, user)

        # Test DPR submitted notification
        dpr = project.dailyprogressreport_set.first()
        if dpr:
            print(f"Sending DPR submitted notification for DPR {dpr.id}...")
            notify_dpr_submitted(dpr)
        else:
            print("No DPRs found for this project")

    except Exception as e:
        print(f"Error during testing: {e}")

if __name__ == '__main__':
    test_notifications()