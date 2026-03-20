#!/usr/bin/env python
import requests
import json

base = 'http://localhost:8000/api'

# Test 1: Admin login and get DPRs
print('=== Test 1: Admin (PMC Head) gets all DPRs ===')
resp = requests.post(f'{base}/token/', json={'username': 'admin', 'password': 'admin@123'})
print(f'Admin login status: {resp.status_code}')
if resp.status_code != 200:
    print(f'Admin login failed: {resp.text}')
else:
    token = resp.json()['access']
    headers = {'Authorization': f'Bearer {token}'}
    dprs = requests.get(f'{base}/operations/reports/', headers=headers).json()
    print(f'Admin sees {len(dprs)} DPRs:')
    for d in dprs:
        print(f'  ID: {d["id"]}, Status: {d["status"]}, Project: {d.get("project_name", "N/A")}, By: {d.get("submitted_by_name", "N/A")}')

# Test 2: Site Engineer login - debug
print('\n=== Test 2: Site Engineer login debug ===')
resp2 = requests.post(f'{base}/token/', json={'username': 'site_engineer', 'password': 'admin@123'})
print(f'Site Engineer login status: {resp2.status_code}')
if resp2.status_code != 200:
    print(f'Site Engineer login failed: {resp2.text}')
else:
    token2 = resp2.json()['access']
    headers2 = {'Authorization': f'Bearer {token2}'}
    dprs2 = requests.get(f'{base}/operations/reports/', headers=headers2).json()
    print(f'Site Engineer sees {len(dprs2)} DPRs (only their own):')
    for d in dprs2:
        print(f'  ID: {d["id"]}, Status: {d["status"]}, By: {d.get("submitted_by_name", "N/A")}')

# Test 3: Create DPR as site engineer
print('\n=== Test 3: Create DPR as site engineer ===')
resp3 = requests.post(f'{base}/token/', json={'username': 'site_engineer', 'password': 'admin@123'})
print(f'Login status: {resp3.status_code}')
if resp3.status_code == 200:
    token3 = resp3.json()['access']
    headers3 = {'Authorization': f'Bearer {token3}'}
    new_dpr = {
        'project': 7,
        'report_date': '2026-03-04',
        'work_done': 'Test work - Foundation completed for Building A',
        'labor_log': {'skilled': 5, 'unskilled': 10, 'operators': 2, 'security': 2},
        'machinery_log': [{'name': 'Tower Crane', 'count': 1, 'status': 'Operational'}],
        'manpower_count': 19,
        'critical_issues': 'None',
        'billing_status': 'Pending',
        'status': 'PENDING'
    }
    created_resp = requests.post(f'{base}/operations/reports/', json=new_dpr, headers=headers3)
    print(f'Create status: {created_resp.status_code}')
    if created_resp.status_code == 201:
        created = created_resp.json()
        print(f'Created DPR: ID={created["id"]}, Status={created["status"]}, By={created.get("submitted_by_name")}')
        new_dpr_id = created["id"]
        
        # Test 4: Admin approves the DPR
        print(f'\n=== Test 4: Admin approves DPR #{new_dpr_id} ===')
        approve_resp = requests.post(f'{base}/operations/reports/{new_dpr_id}/approve/', headers=headers)
        print(f'Approve status: {approve_resp.status_code}')
        if approve_resp.status_code == 200:
            approved = approve_resp.json()
            print(f'DPR Approved: Status={approved["dpr"]["status"]}, Approved By={approved["dpr"].get("approved_by_name")}')
        else:
            print(f'Approve failed: {approve_resp.text}')
    else:
        print(f'Create failed: {created_resp.text}')
else:
    print(f'Site Engineer login failed: {resp3.text}')

print('\n=== Tests completed ===')
