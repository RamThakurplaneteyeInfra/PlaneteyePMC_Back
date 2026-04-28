#!/usr/bin/env python
"""
Test WebSocket connection and Chrome notifications
"""
import requests
import time

def test_websocket_server():
    print("Testing WebSocket-enabled server...")

    # Test HTTP endpoints first
    http_tests = [
        "http://127.0.0.1:8000/",
        "http://127.0.0.1:8000/notifications/test/",
        "http://127.0.0.1:8000/notifications/ch-notification/",
    ]

    print("\n=== Testing HTTP Endpoints ===")
    for url in http_tests:
        try:
            if "ch-notification" in url:
                # This is a POST endpoint, so it will return 405 for GET
                response = requests.post(url, json={"type": "project_created", "project_id": 1})
            else:
                response = requests.get(url)

            print(f"OK {url} - Status: {response.status_code}")
        except Exception as e:
            print(f"ERROR {url} - Error: {e}")

    # Test WebSocket by sending a notification
    print("\n=== Testing Chrome Notification ===")
    try:
        url = "http://127.0.0.1:8000/notifications/ch-notification/"
        data = {
            "type": "project_created",
            "project_id": 1
        }

        print(f"Sending notification: {data}")
        response = requests.post(url, json=data, headers={"Content-Type": "application/json"})

        print(f"Response Status: {response.status_code}")
        print(f"Response: {response.json()}")

        if response.status_code == 200:
            print("SUCCESS: Chrome notification sent successfully!")
            print("Check the browser tab at http://127.0.0.1:8000/notifications/test/ for notifications")
        else:
            print(f"FAILED: Failed to send notification: {response.text}")

    except Exception as e:
        print(f"ERROR: Error testing notification: {e}")

if __name__ == '__main__':
    test_websocket_server()