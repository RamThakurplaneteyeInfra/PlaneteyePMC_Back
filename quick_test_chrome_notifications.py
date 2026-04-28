#!/usr/bin/env python
"""
Quick test script for Chrome notification endpoint - checks if server is running
"""
import requests

def test_endpoint():
    try:
        # Test if server is running
        response = requests.get("http://localhost:8000/notifications/test/")
        if response.status_code == 200:
            print("✅ Server is running")

            # Test Chrome notification endpoint
            data = {"type": "project_created", "project_id": 1}
            response = requests.post(
                "http://localhost:8000/notifications/ch-notification/",
                json=data,
                headers={"Content-Type": "application/json"}
            )
            print(f"Chrome notification test: Status {response.status_code}")
            print(f"Response: {response.text}")
        else:
            print("❌ Server is not running. Start with: python manage.py runserver")
    except Exception as e:
        print(f"❌ Error: {e}")
        print("Make sure Django server is running on localhost:8000")

if __name__ == '__main__':
    test_endpoint()