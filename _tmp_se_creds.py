import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
import django
django.setup()

from django.contrib.auth import get_user_model
from projects.models import Project
from projects.pmc_team_mappings import TL_PROJECT_MAPPINGS

User = get_user_model()

SPECS = [
    ("pmc_se", "Site Engineer", "Pmc@SE", "site_engineer"),
    ("pmc_bse", "Billing Site Engineer", "Pmc@BSE", "billing_site_engineer"),
    ("pmc_qaqc", "QAQC Site Engineer", "Pmc@QA", "qaqc_site_engineer"),
    ("pmc_hse", "HSE Site Engineer", "Pmc@HSE", "hse_site_engineer"),
]

print("index\tusername\tpassword\trole\tproject")
for i, (_tl, mapped_proj) in enumerate(TL_PROJECT_MAPPINGS, start=1):
    for prefix, role, pw_prefix, field in SPECS:
        uname = f"{prefix}{i}"
        password = f"{pw_prefix}{i}"
        u = User.objects.filter(username=uname).first()
        if not u:
            print(f"{i}\t{uname}\tMISSING\t{role}\t{mapped_proj}")
            continue
        p = Project.objects.filter(**{field: u}).first()
        if p is None and field == "site_engineer":
            p = Project.objects.filter(site_engineers=u).first()
        pname = p.name if p else f"(mapped) {mapped_proj}"
        print(f"{i}\t{uname}\t{password}\t{role}\t{pname}")
