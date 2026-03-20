"""
Smoke test for Contract Management Workflow endpoints.

Prereqs:
- Django server running on http://localhost:8000
  (or start it with: python manage.py runserver)
"""

import time
import requests


BASE = "http://localhost:8000"


def wait_for_server():
    for _ in range(30):
        try:
            r = requests.get(f"{BASE}/swagger/", timeout=1)
            if r.status_code in (200, 302):
                return True
        except Exception:
            time.sleep(0.5)
    return False


def main():
    if not wait_for_server():
        raise SystemExit("Server not reachable at http://localhost:8000. Start runserver first.")

    s = requests.Session()

    # 1) Create contract (Billing Site Engineer)
    payload = {
        "role": "Billing Site Engineer",
        "project_name": "Project Alpha",
        "original_contract_value": "1000000.00",
        "approved_vo": "50000.00",
        "pending_vo": "25000.00",
        "created_by": "Billing SE 1",
    }
    r = s.post(f"{BASE}/api/contracts/", json=payload, timeout=10)
    print("POST /api/contracts/ =>", r.status_code)
    print(r.text)
    r.raise_for_status()
    contract_id = r.json()["id"]

    # 2) Dashboard list (approved only) should be empty until approved
    r = s.get(f"{BASE}/api/contracts/", timeout=10)
    print("GET /api/contracts/ =>", r.status_code)
    print(r.text)

    # 3) All contracts (CEO)
    r = s.get(f"{BASE}/api/contracts/all/", params={"role": "CEO"}, timeout=10)
    print("GET /api/contracts/all/?role=CEO =>", r.status_code)
    print(r.text)
    r.raise_for_status()

    # 4) Approve (CEO)
    r = s.post(f"{BASE}/api/contracts/{contract_id}/approve/", json={"role": "CEO"}, timeout=10)
    print("POST /api/contracts/{id}/approve/ =>", r.status_code)
    print(r.text)
    r.raise_for_status()

    # 5) Dashboard list now should show Project Alpha
    r = s.get(f"{BASE}/api/contracts/", timeout=10)
    print("GET /api/contracts/ (after approve) =>", r.status_code)
    print(r.text)

    # 6) Summary totals
    r = s.get(f"{BASE}/api/contracts/summary/", timeout=10)
    print("GET /api/contracts/summary/ =>", r.status_code)
    print(r.text)

    # 7) Reject path: create a second and reject
    payload2 = {
        "role": "Billing Site Engineer",
        "project_name": "Project Beta",
        "original_contract_value": "200000.00",
        "approved_vo": "10000.00",
        "pending_vo": "5000.00",
        "created_by": "Billing SE 2",
    }
    r = s.post(f"{BASE}/api/contracts/", json=payload2, timeout=10)
    print("POST /api/contracts/ (#2) =>", r.status_code)
    print(r.text)
    r.raise_for_status()
    contract2_id = r.json()["id"]

    r = s.post(f"{BASE}/api/contracts/{contract2_id}/reject/", json={"role": "CEO"}, timeout=10)
    print("POST /api/contracts/{id}/reject/ =>", r.status_code)
    print(r.text)
    r.raise_for_status()

    # 8) Filter by project_name
    r = s.get(f"{BASE}/api/contracts/", params={"project_name": "Alpha"}, timeout=10)
    print("GET /api/contracts/?project_name=Alpha =>", r.status_code)
    print(r.text)

    print("\n[OK] Contract endpoints smoke test completed.")


if __name__ == "__main__":
    main()

