from django.contrib.auth import get_user_model

from projects.models import Project

U = get_user_model()
p = Project.objects.get(id=64)
print("RGSL", p.name, p.status)
print("TL", getattr(p.team_lead, "username", None))
print("SE", getattr(p.site_engineer, "username", None))
print("BSE", getattr(p.billing_site_engineer, "username", None))
print("QAQC", getattr(p.qaqc_site_engineer, "username", None))
print("HSE", getattr(p.hse_site_engineer, "username", None))
khb = Project.objects.filter(name__icontains="KHB Multiplex").first()
print("KHB", khb.name if khb else None)
print("KHB TL", getattr(khb.team_lead, "username", None) if khb else None)
print("KHB SE", getattr(khb.site_engineer, "username", None) if khb else None)
print("tl1 leads", list(U.objects.get(username="pmc_tl1").lead_projects.values_list("name", flat=True)))
print("tl26 exists", U.objects.filter(username="pmc_tl26").exists())
print("tl27 exists", U.objects.filter(username="pmc_tl27").exists())
