from django.contrib.auth import get_user_model
from django.db.models import ProtectedError

from projects.models import Project

U = get_user_model()
qs = Project.objects.filter(name__iexact="SHIVALIKA") | Project.objects.filter(name__icontains="SHIVALIKA")
for p in qs.distinct().order_by("id"):
    print(
        "FOUND",
        p.id,
        repr(p.name),
        p.status,
        "TL=",
        getattr(p.team_lead, "username", None),
        "SE=",
        getattr(p.site_engineer, "username", None),
        "BSE=",
        getattr(p.billing_site_engineer, "username", None),
        "QAQC=",
        getattr(p.qaqc_site_engineer, "username", None),
        "HSE=",
        getattr(p.hse_site_engineer, "username", None),
    )

tl = U.objects.filter(username="pmc_tl25").first()
if tl:
    print("tl25 leads:", list(tl.lead_projects.values_list("id", "name")))
