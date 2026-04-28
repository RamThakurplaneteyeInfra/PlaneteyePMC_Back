#!/usr/bin/env python
"""
Test if the Django server is running and URLs are accessible
"""
import requests
import time

def test_server():
    print("Testing Django server...")

    urls_to_test = [
        "http://127.0.0.1:8000/",
        "http://127.0.0.1:8000/notifications/test/",
        "http://127.0.0.1:8000/notifications/ch-notification/",
        "http://localhost:8000/notifications/test/",
    ]

    for url in urls_to_test:
        try:
            print(f"\nTesting: {url}")
            response = requests.get(url, timeout=5)
            print(f"Status: {response.status_code}")
            if response.status_code == 200:
                print("SUCCESS - URL is accessible")
                if "notifications" in url:
                    print(f"Content length: {len(response.text)}")
            else:
                print(f"Content: {response.text[:200]}...")
        except requests.exceptions.RequestException as e:
            print(f"ERROR - Could not connect: {e}")
        time.sleep(1)

if __name__ == '__main__':
    test_server()