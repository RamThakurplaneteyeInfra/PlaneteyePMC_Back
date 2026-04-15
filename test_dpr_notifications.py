#!/usr/bin/env python
import os
import django
import sys

# Setup Django
sys.path.append('/path/to/your/backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()

from dpr.models import DailyProgressReport
from services.notifications import notify_dpr_submitted, notify_dpr_approved_by_role, notify_dpr_rejected_by_role
from django.contrib.auth.models import User
from django.utils import timezone

def test_dpr_notifications():
    # Test DPR Submitted
    print("Testing DPR Submitted Notification...")
    try:
        dpr = DailyProgressReport.objects.get(id=85)
        result = notify_dpr_submitted(dpr)
        print("[OK] DPR Submitted notification sent successfully")
    except Exception as e:
        print(f"[ERROR] {e}")

    # Test DPR Approved by Team Lead
    print("\nTesting DPR Approved by Team Lead...")
    try:
        dpr = DailyProgressReport.objects.get(id=85)
        # Simulate Team Lead approval
        from django.utils import timezone
        approver = User.objects.get(username='pmc_tl')  # Team Lead
        dpr.approved_by = approver
        dpr.approved_at = timezone.now()
        dpr.save()
        result = notify_dpr_approved_by_role(dpr, 'Team Leader')
        print("[OK] DPR Team Lead approval notification sent successfully")
    except Exception as e:
        print(f"[ERROR] {e}")

    # Test DPR Approved by Coordinator
    print("\nTesting DPR Approved by Coordinator...")
    try:
        dpr = DailyProgressReport.objects.get(id=85)
        coordinator = User.objects.get(username='pmc_coordinator')  # Coordinator
        dpr.approved_by = coordinator
        dpr.approved_at = timezone.now()
        dpr.save()
        result = notify_dpr_approved_by_role(dpr, 'Coordinator')
        print("[OK] DPR Coordinator approval notification sent successfully")
    except Exception as e:
        print(f"[ERROR] {e}")

    # Test DPR Rejected by Team Lead
    print("\nTesting DPR Rejected by Team Lead...")
    try:
        dpr = DailyProgressReport.objects.get(id=85)
        rejector = User.objects.get(username='pmc_tl')  # Team Lead
        dpr.rejected_by = rejector
        dpr.rejection_reason = "Test rejection reason by Team Lead"
        dpr.save()
        result = notify_dpr_rejected_by_role(dpr, 'Team Leader')
        print("[OK] DPR Team Lead rejection notification sent successfully")
    except Exception as e:
        print(f"[ERROR] {e}")

if __name__ == "__main__":
    test_dpr_notifications()