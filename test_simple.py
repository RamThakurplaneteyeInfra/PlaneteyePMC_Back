#!/usr/bin/env python
import requests

try:
    response = requests.get('http://localhost:8000/notifications/test/')
    print(f'Status: {response.status_code}')
    print(f'Content-Type: {response.headers.get("content-type")}')
    print(f'Response length: {len(response.text)}')
    if response.status_code == 200:
        print('First 200 chars:', response.text[:200])
except Exception as e:
    print(f'Error: {e}')