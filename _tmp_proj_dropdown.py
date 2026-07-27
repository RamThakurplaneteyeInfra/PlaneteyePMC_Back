from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from accounts.rbac import get_user_assigned_projects_qs, is_admin_user
from projects.models import Project

print("=== Recent projects ===")
for p in Project.objects.order_by("-id")[:15]:
    print(
        f"id={p.id} status={p.status!r} name={p.name!r} "
        f"TL={getattr(p.team_lead, 'username', None)} "
        f"SE={getattr(p.site_engineer, 'username', None)}"
    )

print("\n=== Status counts ===")
from django.db.models import Count
for row in Project.objects.values("status").annotate(c=Count("id")).order_by("status"):
    print(row)

print("\n=== Visibility checks ===")
User = get_user_model()
for uname in ["pmc_ho", "pmc_head", "pmc_tl27", "pmc_manager", "pmc_tl24"]:
    u = User.objects.filter(username=uname).first()
    if not u:
        print(uname, "MISSING")
        continue
    qs = get_user_assigned_projects_qs(u)
    recent_visible = list(qs.order_by("-id")[:8].values_list("id", "name", "status"))
    print(
        f"{uname}: admin={is_admin_user(u)} count={qs.count()} "
        f"has_rgsl={qs.filter(name__icontains='RGSL').exists()} "
        f"recent={recent_visible}"
    )

# Any project in planning with no assignment?
print("\n=== Unassigned / planning projects ===")
for p in Project.objects.filter(status="planning").order_by("-id")[:20]:
    assigned = any(
        [
            p.team_lead_id,
            p.site_engineer_id,
            p.billing_site_engineer_id,
            p.qaqc_site_engineer_id,
            p.hse_site_engineer_id,
            p.site_engineers.exists(),
            p.assigned_users.exists(),
            p.coordinators.exists(),
            p.pmc_head_id,
        ]
    )
    print(f"id={p.id} name={p.name!r} assigned_any={assigned}")
