#!/usr/bin/env python
"""
Test if the notification endpoints are properly configured
"""
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()

from django.urls import reverse
from django.test import Client

def test_notification_urls():
    print("Testing notification URLs...")

    client = Client()

    # Test notification test page
    try:
        response = client.get('/notifications/test/')
        print(f"OK /notifications/test/ - Status: {response.status_code}")
    except Exception as e:
        print(f"ERROR /notifications/test/ - Error: {e}")

    # Test Chrome notification endpoint
    try:
        response = client.post('/notifications/ch-notification/',
                              data='{"type": "project_created", "project_id": 1}',
                              content_type='application/json')
        print(f"OK /notifications/ch-notification/ - Status: {response.status_code}")
        print(f"Response: {response.content.decode()}")
    except Exception as e:
        print(f"ERROR /notifications/ch-notification/ - Error: {e}")

    # Test URL resolution
    try:
        from django.urls import resolve
        match = resolve('/notifications/test/')
        print(f"OK URL resolution works: {match.url_name}")
    except Exception as e:
        print(f"ERROR URL resolution failed: {e}")

if __name__ == '__main__':
    test_notification_urls()