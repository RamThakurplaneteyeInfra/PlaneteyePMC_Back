from django.contrib.auth import get_user_model

from accounts.rbac import get_user_assigned_projects_qs
from projects.models import Project

User = get_user_model()
rgsl = Project.objects.get(id=64)
se1 = User.objects.get(username="pmc_se1")

print("Before M2M:", list(rgsl.site_engineers.values_list("username", flat=True)))
rgsl.site_engineers.remove(se1)
# Keep only the correctly assigned primary SE (and any legit *27 engineers)
keep = set()
for uname in [
    getattr(rgsl.site_engineer, "username", None),
    getattr(rgsl.billing_site_engineer, "username", None),
    getattr(rgsl.qaqc_site_engineer, "username", None),
    getattr(rgsl.hse_site_engineer, "username", None),
]:
    if uname:
        keep.add(uname)

# Remove any other stray engineers not in keep (except keep empty means leave alone if no SE FK)
extra = list(rgsl.site_engineers.exclude(username__in=keep or ["__none__"]))
for u in extra:
    # Only remove if clearly wrong prefix index mismatch with assigned team
    if u.username.startswith("pmc_se") and u.username != getattr(rgsl.site_engineer, "username", None):
        rgsl.site_engineers.remove(u)
        print("Removed stray", u.username)

print("After M2M:", list(rgsl.site_engineers.values_list("username", flat=True)))

# Ensure primary SE is on M2M
if rgsl.site_engineer_id:
    rgsl.site_engineers.add(rgsl.site_engineer)

print("Final M2M:", list(rgsl.site_engineers.values_list("username", flat=True)))

for uname in ["pmc_se1", "pmc_se27"]:
    u = User.objects.get(username=uname)
    names = list(get_user_assigned_projects_qs(u).values_list("name", flat=True))
    print(uname, "projects=", names, "has_rgsl=", any("RGSL" in n for n in names))
