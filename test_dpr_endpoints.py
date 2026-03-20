"""
Comprehensive test script for DPR API endpoints
Tests all CRUD operations and filtering
"""
import requests
import json
from datetime import date, timedelta

BASE_URL = "http://localhost:8000/api"

def print_section(title):
    """Print a formatted section header"""
    print("\n" + "="*60)
    print(f"  {title}")
    print("="*60)

def print_response(response, show_body=True):
    """Print response details"""
    print(f"Status Code: {response.status_code}")
    if show_body:
        try:
            print(f"Response: {json.dumps(response.json(), indent=2)}")
        except:
            print(f"Response: {response.text}")
    print("-"*60)

def test_create_dpr():
    """Test POST /api/dpr/ - Create a new DPR"""
    print_section("TEST 1: Create DPR (POST /api/dpr/)")
    
    dpr_data = {
        "project_name": "Test Highway Construction Project",
        "job_no": "TEST-JOB-001",
        "report_date": str(date.today()),
        "unresolved_issues": "Material delivery delayed by 2 days",
        "pending_letters": "Letter to client regarding site access",
        "quality_status": "All quality checks passed successfully",
        "next_day_incident": "Concrete pouring scheduled for foundation",
        "bill_status": "Invoice #TEST-1234 submitted to client",
        "gfc_status": "GFC drawings approved by client",
        "issued_by": "Test Engineer",
        "designation": "Site Engineer",
        "activities": [
            {
                "date": str(date.today()),
                "activity": "Foundation excavation work",
                "deliverables": "500 cubic meters of earth excavated",
                "target_achieved": 85.5,
                "next_day_plan": "Continue excavation work and prepare for concrete",
                "remarks": "Weather conditions were favorable"
            },
            {
                "date": str(date.today()),
                "activity": "Steel reinforcement installation",
                "deliverables": "50 tons of steel reinforcement installed",
                "target_achieved": 92.0,
                "next_day_plan": "Complete remaining reinforcement work",
                "remarks": "Work is on schedule"
            }
        ]
    }
    
    response = requests.post(f"{BASE_URL}/dpr/", json=dpr_data)
    print_response(response)
    
    if response.status_code == 201:
        dpr = response.json()
        print(f"[SUCCESS] DPR created successfully with ID: {dpr['id']}")
        return dpr['id']
    else:
        print("[FAILED] Failed to create DPR")
        return None

def test_list_dprs():
    """Test GET /api/dpr/ - List all DPRs"""
    print_section("TEST 2: List All DPRs (GET /api/dpr/)")
    
    response = requests.get(f"{BASE_URL}/dpr/")
    print_response(response, show_body=False)
    
    if response.status_code == 200:
        data = response.json()
        count = data.get('count', len(data.get('results', [])))
        print(f"[SUCCESS] Successfully retrieved {count} DPR(s)")
        if 'results' in data and len(data['results']) > 0:
            print(f"   First DPR ID: {data['results'][0]['id']}")
            return data['results'][0]['id']
    else:
        print("[FAILED] Failed to list DPRs")
    return None

def test_get_single_dpr(dpr_id):
    """Test GET /api/dpr/{id}/ - Get single DPR"""
    print_section(f"TEST 3: Get Single DPR (GET /api/dpr/{dpr_id}/)")
    
    if not dpr_id:
        print("[SKIP] Skipping - No DPR ID available")
        return
    
    response = requests.get(f"{BASE_URL}/dpr/{dpr_id}/")
    print_response(response, show_body=False)
    
    if response.status_code == 200:
        dpr = response.json()
        print(f"[SUCCESS] Successfully retrieved DPR ID: {dpr['id']}")
        print(f"   Project: {dpr['project_name']}")
        print(f"   Activities: {len(dpr.get('activities', []))}")
    else:
        print("[FAILED] Failed to get DPR")

def test_filter_by_project_name():
    """Test GET /api/dpr/?project_name=... - Filter by project name"""
    print_section("TEST 4: Filter by Project Name (GET /api/dpr/?project_name=Test)")
    
    response = requests.get(f"{BASE_URL}/dpr/", params={"project_name": "Test"})
    print_response(response, show_body=False)
    
    if response.status_code == 200:
        data = response.json()
        count = data.get('count', len(data.get('results', [])))
        print(f"[SUCCESS] Found {count} DPR(s) matching 'Test'")
    else:
        print("[FAILED] Failed to filter DPRs")

def test_filter_by_date():
    """Test GET /api/dpr/?date=... - Filter by date"""
    print_section("TEST 5: Filter by Date (GET /api/dpr/?date=...)")
    
    today = str(date.today())
    response = requests.get(f"{BASE_URL}/dpr/", params={"date": today})
    print_response(response, show_body=False)
    
    if response.status_code == 200:
        data = response.json()
        count = data.get('count', len(data.get('results', [])))
        print(f"[SUCCESS] Found {count} DPR(s) for date: {today}")
    else:
        print("[FAILED] Failed to filter by date")

def test_filter_by_date_range():
    """Test GET /api/dpr/?date_from=...&date_to=... - Filter by date range"""
    print_section("TEST 6: Filter by Date Range")
    
    date_from = str(date.today() - timedelta(days=7))
    date_to = str(date.today())
    
    response = requests.get(
        f"{BASE_URL}/dpr/",
        params={"date_from": date_from, "date_to": date_to}
    )
    print_response(response, show_body=False)
    
    if response.status_code == 200:
        data = response.json()
        count = data.get('count', len(data.get('results', [])))
        print(f"[SUCCESS] Found {count} DPR(s) between {date_from} and {date_to}")
    else:
        print("[FAILED] Failed to filter by date range")

def test_update_dpr(dpr_id):
    """Test PUT /api/dpr/{id}/ - Update DPR (full update)"""
    print_section(f"TEST 7: Update DPR (PUT /api/dpr/{dpr_id}/)")
    
    if not dpr_id:
        print("[SKIP] Skipping - No DPR ID available")
        return
    
    update_data = {
        "project_name": "Updated Test Highway Construction Project",
        "job_no": "TEST-JOB-001-UPDATED",
        "report_date": str(date.today()),
        "unresolved_issues": "Material delivery resolved",
        "pending_letters": "All letters sent",
        "quality_status": "All quality checks passed - Updated",
        "next_day_incident": "Concrete pouring completed",
        "bill_status": "Invoice #TEST-1234 approved",
        "gfc_status": "GFC drawings approved and implemented",
        "issued_by": "Updated Test Engineer",
        "designation": "Senior Site Engineer",
        "activities": [
            {
                "date": str(date.today()),
                "activity": "Updated foundation excavation work",
                "deliverables": "600 cubic meters excavated",
                "target_achieved": 90.0,
                "next_day_plan": "Begin concrete pouring",
                "remarks": "Progress updated successfully"
            }
        ]
    }
    
    response = requests.put(f"{BASE_URL}/dpr/{dpr_id}/", json=update_data)
    print_response(response, show_body=False)
    
    if response.status_code == 200:
        dpr = response.json()
        print(f"[SUCCESS] Successfully updated DPR ID: {dpr['id']}")
        print(f"   Updated Project: {dpr['project_name']}")
    else:
        print("[FAILED] Failed to update DPR")

def test_partial_update_dpr(dpr_id):
    """Test PATCH /api/dpr/{id}/ - Partial update"""
    print_section(f"TEST 8: Partial Update DPR (PATCH /api/dpr/{dpr_id}/)")
    
    if not dpr_id:
        print("[SKIP] Skipping - No DPR ID available")
        return
    
    partial_data = {
        "project_name": "Partially Updated Project Name",
        "quality_status": "Partially updated quality status"
    }
    
    response = requests.patch(f"{BASE_URL}/dpr/{dpr_id}/", json=partial_data)
    print_response(response, show_body=False)
    
    if response.status_code == 200:
        dpr = response.json()
        print(f"[SUCCESS] Successfully partially updated DPR ID: {dpr['id']}")
        print(f"   Updated Project: {dpr['project_name']}")
    else:
        print("[FAILED] Failed to partially update DPR")

def test_get_activities(dpr_id):
    """Test GET /api/dpr/{id}/activities/ - Get activities for a DPR"""
    print_section(f"TEST 9: Get Activities (GET /api/dpr/{dpr_id}/activities/)")
    
    if not dpr_id:
        print("[SKIP] Skipping - No DPR ID available")
        return
    
    response = requests.get(f"{BASE_URL}/dpr/{dpr_id}/activities/")
    print_response(response, show_body=False)
    
    if response.status_code == 200:
        activities = response.json()
        print(f"[SUCCESS] Successfully retrieved {len(activities)} activity/activities")
        if activities:
            print(f"   First activity: {activities[0].get('activity', 'N/A')}")
    else:
        print("[FAILED] Failed to get activities")

def test_pagination():
    """Test GET /api/dpr/?page=... - Pagination"""
    print_section("TEST 10: Test Pagination (GET /api/dpr/?page=1)")
    
    response = requests.get(f"{BASE_URL}/dpr/", params={"page": 1})
    print_response(response, show_body=False)
    
    if response.status_code == 200:
        data = response.json()
        count = data.get('count', 0)
        next_page = data.get('next')
        print(f"[SUCCESS] Pagination working")
        print(f"   Total count: {count}")
        print(f"   Next page: {'Yes' if next_page else 'No'}")
    else:
        print("[FAILED] Failed to test pagination")

def test_validation_error():
    """Test validation - target_achieved > 100 should fail"""
    print_section("TEST 11: Test Validation (target_achieved > 100)")
    
    invalid_data = {
        "project_name": "Validation Test",
        "job_no": "VALID-001",
        "report_date": str(date.today()),
        "issued_by": "Test User",
        "designation": "Engineer",
        "activities": [
            {
                "date": str(date.today()),
                "activity": "Test activity",
                "target_achieved": 150.0  # Invalid - should be 0-100
            }
        ]
    }
    
    response = requests.post(f"{BASE_URL}/dpr/", json=invalid_data)
    print_response(response)
    
    if response.status_code == 400:
        print("[SUCCESS] Validation working correctly - rejected invalid target_achieved")
    else:
        print("[FAILED] Validation not working - should have rejected target_achieved > 100")

def test_delete_dpr(dpr_id):
    """Test DELETE /api/dpr/{id}/ - Delete DPR"""
    print_section(f"TEST 12: Delete DPR (DELETE /api/dpr/{dpr_id}/)")
    
    if not dpr_id:
        print("[SKIP] Skipping - No DPR ID available")
        return
    
    response = requests.delete(f"{BASE_URL}/dpr/{dpr_id}/")
    print_response(response)
    
    if response.status_code == 200:
        print(f"[SUCCESS] Successfully deleted DPR ID: {dpr_id}")
    else:
        print("[FAILED] Failed to delete DPR")

def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("  DPR API ENDPOINT TESTING")
    print("="*60)
    print(f"\nTesting endpoints at: {BASE_URL}/dpr/")
    print("Note: No authentication required for DPR endpoints\n")
    
    # Check if server is running
    try:
        response = requests.get(f"{BASE_URL}/dpr/", timeout=5)
    except requests.exceptions.ConnectionError:
        print("[ERROR] Cannot connect to server!")
        print("   Please make sure the Django server is running:")
        print("   python manage.py runserver")
        return
    except Exception as e:
        print(f"[ERROR] {e}")
        return
    
    # Run tests
    dpr_id = test_create_dpr()
    test_list_dprs()
    
    # Get a DPR ID if we don't have one from creation
    if not dpr_id:
        dpr_id = test_list_dprs()
    
    test_get_single_dpr(dpr_id)
    test_filter_by_project_name()
    test_filter_by_date()
    test_filter_by_date_range()
    test_update_dpr(dpr_id)
    test_partial_update_dpr(dpr_id)
    test_get_activities(dpr_id)
    test_pagination()
    test_validation_error()
    
    # Delete test DPR at the end
    print("\n" + "="*60)
    print("  CLEANUP: Deleting test DPR")
    print("="*60)
    test_delete_dpr(dpr_id)
    
    print("\n" + "="*60)
    print("  TESTING COMPLETE")
    print("="*60)
    print("\nAll tests executed. Check results above for any failures.\n")

if __name__ == "__main__":
    main()
