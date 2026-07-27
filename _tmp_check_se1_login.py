from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.models import Group

from accounts.models import UserProfile
from accounts.rbac import get_user_assigned_projects_qs
from projects.models import Project

User = get_user_model()

candidates = ["pmc_se1", "pmc_se", "site1", "se1"]
print("=== users matching site engineer 1 patterns ===")
for u in User.objects.filter(username__icontains="se1").order_by("username")[:30]:
    groups = list(u.groups.values_list("name", flat=True))
    print(
        f"id={u.id} username={u.username!r} active={u.is_active} "
        f"staff={u.is_staff} groups={groups} last_login={u.last_login}"
    )

u = User.objects.filter(username="pmc_se1").first()
if not u:
    print("pmc_se1 MISSING")
else:
    print("\n=== pmc_se1 detail ===")
    print("active", u.is_active)
    print("groups", list(u.groups.values_list("name", flat=True)))
    try:
        p = u.profile
        print("designation", p.designation, "type", p.site_engineer_type)
    except UserProfile.DoesNotExist:
        print("NO PROFILE")

    # Try common password patterns used in this project
    passwords = [
        "Pmc@SE1",
        "Pmc@SE01",
        "Pmc@se1",
        "pmc@SE1",
        "Project@123",
        "testpass123",
        "tl@1",
        "Pmc@TL1",
    ]
    print("\n=== password checks ===")
    for pw in passwords:
        ok = authenticate(username="pmc_se1", password=pw) is not None
        print(f"{pw!r}: {ok}")

    print("\n=== assigned projects ===")
    print(list(get_user_assigned_projects_qs(u).values_list("id", "name")))

# Also check if someone deactivated se1 recently
print("\n=== Site Engineer group users active counts ===")
se_group = Group.objects.filter(name="Site Engineer").first()
if se_group:
    qs = User.objects.filter(groups=se_group)
    print("total", qs.count(), "active", qs.filter(is_active=True).count(), "inactive", qs.filter(is_active=False).count())
    inactive = list(qs.filter(is_active=False).values_list("username", flat=True)[:20])
    print("inactive usernames", inactive)
