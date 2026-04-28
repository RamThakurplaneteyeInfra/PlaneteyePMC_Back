#!/usr/bin/env python
"""
Test script for the unified Chrome notification endpoint
"""
import os
import sys
import django
import requests
import json

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()

def test_chrome_notifications():
    print("Testing unified Chrome notification endpoint...")

    base_url = "http://localhost:8000"
    endpoint = f"{base_url}/notifications/ch-notification/"

    # Test cases
    test_cases = [
        {
            "name": "Project Created",
            "data": {"type": "project_created", "project_id": 1}
        },
        {
            "name": "Project Assigned to Team Leader",
            "data": {"type": "project_assigned", "project_id": 1, "user_id": 2}
        },
        {
            "name": "Site Engineer Assigned",
            "data": {"type": "site_engineer_assigned", "project_id": 1, "user_id": 3}
        },
        {
            "name": "DPR Submitted",
            "data": {"type": "dpr_submitted", "dpr_id": 85}
        },
        {
            "name": "DPR Approved",
            "data": {"type": "dpr_approved", "dpr_id": 85}
        },
        {
            "name": "DPR Rejected",
            "data": {"type": "dpr_rejected", "dpr_id": 85}
        }
    ]

    headers = {"Content-Type": "application/json"}

    for test_case in test_cases:
        print(f"\nTesting: {test_case['name']}")
        try:
            response = requests.post(endpoint, json=test_case['data'], headers=headers)
            print(f"Status: {response.status_code}")
            print(f"Response: {response.json()}")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == '__main__':
    test_chrome_notifications()