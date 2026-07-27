from django.contrib.auth import get_user_model

from accounts.rbac import get_user_assigned_projects_qs, is_admin_user
from projects.models import Project

User = get_user_model()
rgsl = Project.objects.filter(name__icontains="RGSL").first()
print("RGSL", rgsl.id if rgsl else None, repr(rgsl.name) if rgsl else None)
if rgsl:
    print("TL", getattr(rgsl.team_lead, "username", None))
    print("SE FK", getattr(rgsl.site_engineer, "username", None))
    print("BSE", getattr(rgsl.billing_site_engineer, "username", None))
    print("QAQC", getattr(rgsl.qaqc_site_engineer, "username", None))
    print("HSE", getattr(rgsl.hse_site_engineer, "username", None))
    print("SE M2M", list(rgsl.site_engineers.values_list("username", flat=True)))
    print("assigned_users", list(rgsl.assigned_users.values_list("username", flat=True)))
    print("coordinators", list(rgsl.coordinators.values_list("username", flat=True)))
    print("pmc_head", getattr(rgsl.pmc_head, "username", None))

for uname in ["pmc_se1", "pmc_se27", "pmc_bse1", "pmc_bse27", "pmc_tl1", "pmc_tl27"]:
    u = User.objects.filter(username=uname).first()
    if not u:
        print(uname, "MISSING")
        continue
    qs = get_user_assigned_projects_qs(u)
    names = list(qs.values_list("name", flat=True))
    print(uname, "admin=", is_admin_user(u), "count=", qs.count(), "has_rgsl=", any("RGSL" in n for n in names), "projects=", names[:10])
