#!/usr/bin/env python
"""
Test script to check what users and projects exist for testing
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()

from django.contrib.auth.models import User
from projects.models import Project
from dpr.models import DailyProgressReport

def check_test_data():
    print("=== Available Test Data ===")

    print("\nUsers:")
    for user in User.objects.all()[:10]:  # First 10 users
        groups = user.groups.all()
        group_names = [g.name for g in groups]
        print(f"  ID: {user.id}, Username: {user.username}, Groups: {group_names}")

    print("\nProjects:")
    for project in Project.objects.all()[:5]:  # First 5 projects
        coordinators = project.coordinators.all()
        coord_names = [c.username for c in coordinators]
        print(f"  ID: {project.id}, Name: {project.name}")
        print(f"    Team Lead: {project.team_lead.username if project.team_lead else 'None'}")
        print(f"    PMC Head: {project.pmc_head.username if project.pmc_head else 'None'}")
        print(f"    Coordinators: {coord_names}")

    print("\nDPRs:")
    for dpr in DailyProgressReport.objects.all()[:3]:  # First 3 DPRs
        print(f"  ID: {dpr.id}, Project: {dpr.project_name}, Status: {dpr.status}")
        print(f"    Submitted by: {dpr.submitted_by.username if dpr.submitted_by else 'None'}")
        print(f"    Current approver role: {dpr.current_approver_role}")

if __name__ == '__main__':
    check_test_data()