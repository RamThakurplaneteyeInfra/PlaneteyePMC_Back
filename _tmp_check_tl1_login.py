from django.contrib.auth import authenticate, get_user_model
from django.test import Client

from accounts.models import UserProfile
from accounts.rbac import get_user_assigned_projects_qs

User = get_user_model()
u = User.objects.filter(username="pmc_tl1").first()
if not u:
    print("pmc_tl1 MISSING")
else:
    print("active", u.is_active)
    print("groups", list(u.groups.values_list("name", flat=True)))
    try:
        p = u.profile
        print("designation", p.designation)
    except UserProfile.DoesNotExist:
        print("NO PROFILE")

    passwords = [
        "Pmc@TL1",
        "tl@1",
        "Project@123",
        "testpass123",
        "Pmc@SE1",
    ]
    print("=== password checks (before reset) ===")
    for pw in passwords:
        print(repr(pw), authenticate(username="pmc_tl1", password=pw) is not None)

    # Align to earlier TL password pattern used for most TLs
    u.set_password("Pmc@TL1")
    u.is_active = True
    u.save(update_fields=["password", "is_active"])
    print("auth after reset Pmc@TL1", authenticate(username="pmc_tl1", password="Pmc@TL1") is not None)
    print("projects", list(get_user_assigned_projects_qs(u).values_list("id", "name")))

    c = Client()
    for payload in [
        {"username": "pmc_tl1", "password": "Pmc@TL1"},
        {"username": "pmc_tl1", "password": "tl@1"},
        {"username": "pmc_tl1", "password": "Project@123"},
        {"username": "PMC_TL1", "password": "Pmc@TL1"},
    ]:
        r = c.post("/api/token/", data=payload, content_type="application/json")
        print("payload", payload, "status", r.status_code)
        if r.status_code != 200:
            print(" body", r.json())
        else:
            print(" keys", list(r.json().keys()))
