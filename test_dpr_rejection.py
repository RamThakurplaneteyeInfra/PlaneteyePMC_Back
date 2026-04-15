#!/usr/bin/env python
"""
Test script for DPR rejection with proper authentication
Run this directly: python test_dpr_rejection.py
"""

import requests

# Configuration
BASE_URL = "http://127.0.0.1:8000"
USERNAME = "pmc_head"
PASSWORD = "Project@123"
DPR_ID = 86

def test_dpr_rejection():
    print("Testing DPR Rejection with Authentication")
    print("=" * 50)

    # Basic auth is used for all requests
    auth = (USERNAME, PASSWORD)

    # Step 1: Test DPR rejection
    print("1. Testing DPR rejection...")

    headers = {
        "Content-Type": "application/json"
    }

    rejection_data = {
        "rejection_reason": "Test rejection with proper auth"
    }

    rejection_response = requests.post(
        f"{BASE_URL}/api/dpr/{DPR_ID}/reject/",
        headers=headers,
        json=rejection_data,
        auth=auth
    )

    print(f"Status Code: {rejection_response.status_code}")

    if rejection_response.status_code == 200:
        print("SUCCESS: DPR rejection successful!")
        print("Response:", rejection_response.json())

        # Check if DPR status was updated
        check_response = requests.get(
            f"{BASE_URL}/api/dpr/{DPR_ID}/",
            headers=headers,
            auth=auth
        )

        if check_response.status_code == 200:
            dpr_data = check_response.json()
            print(f"SUCCESS: DPR Status: {dpr_data.get('status')}")
            print(f"SUCCESS: Rejected by: {dpr_data.get('rejected_by')}")
            print(f"SUCCESS: Rejection reason: {dpr_data.get('rejection_reason')}")

    else:
        print("ERROR: DPR rejection failed!")
        print("Response:", rejection_response.text)

if __name__ == "__main__":
    test_dpr_rejection()