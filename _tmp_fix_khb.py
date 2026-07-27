from django.contrib.auth import get_user_model

from projects.models import Project

U = get_user_model()
for p in Project.objects.filter(name__icontains="KHB").order_by("id"):
    print(
        p.id,
        repr(p.name),
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

# Ensure mapped KHB has full *1 team
name = "KHB Multiplex, Kengeri (A-3462)"
khb = Project.objects.filter(name=name).first()
if khb is None:
    khb = Project.objects.filter(name__iexact=name).first()
print("TARGET", khb.id if khb else None, repr(khb.name) if khb else None)

if khb:
    mapping = {
        "team_lead": "pmc_tl1",
        "site_engineer": "pmc_se1",
        "billing_site_engineer": "pmc_bse1",
        "qaqc_site_engineer": "pmc_qaqc1",
        "hse_site_engineer": "pmc_hse1",
    }
    changed = []
    for field, uname in mapping.items():
        u = U.objects.filter(username=uname).first()
        if u and getattr(khb, f"{field}_id") != u.id:
            setattr(khb, field, u)
            changed.append(field)
            if field == "site_engineer":
                khb.site_engineers.add(u)
    if changed:
        khb.save(update_fields=[*changed, "updated_at"])
        print("Restored fields:", changed)
    else:
        print("KHB already fully assigned")
    print(
        "FINAL",
        getattr(khb.team_lead, "username", None),
        getattr(khb.site_engineer, "username", None),
        getattr(khb.billing_site_engineer, "username", None),
        getattr(khb.qaqc_site_engineer, "username", None),
        getattr(khb.hse_site_engineer, "username", None),
    )
