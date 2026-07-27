"""One-off: fix RGSL team assignment without colliding with pmc_tl1."""
import re

from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.models import Group

from accounts.models import UserProfile
from projects.models import Project
from projects.pmc_team_mappings import TL_PROJECT_MAPPINGS

User = get_user_model()
PROJECT_NAME = "B3482 RGSL: Rajeev Gandhi Sea Link"

idxs = []
for u in User.objects.filter(username__startswith="pmc_tl").values_list("username", flat=True):
    m = re.fullmatch(r"pmc_tl(\d+)", u)
    if m:
        idxs.append(int(m.group(1)))
for tl, _ in TL_PROJECT_MAPPINGS:
    m = re.fullmatch(r"pmc_tl(\d+)", tl)
    if m:
        idxs.append(int(m.group(1)))
index = (max(idxs) if idxs else 0) + 1
print("Using index", index, "max_existing", max(idxs) if idxs else None)

# Restore pmc_tl1 to original mapped project if we stole it
tl1_project_name = dict(TL_PROJECT_MAPPINGS).get("pmc_tl1")
tl1 = User.objects.filter(username="pmc_tl1").first()
rgsl = Project.objects.get(name=PROJECT_NAME)

if tl1 and rgsl.team_lead_id == tl1.id and tl1_project_name:
    orig = Project.objects.filter(name=tl1_project_name).first()
    if orig and orig.team_lead_id != tl1.id:
        orig.team_lead = tl1
        orig.save(update_fields=["team_lead", "updated_at"])
        print(f"Restored pmc_tl1 -> {orig.name} (id={orig.id})")
    # Clear stolen SE/BSE/QAQC/HSE from RGSL if they are *1 users
    cleared = False
    for field, uname in [
        ("site_engineer", "pmc_se1"),
        ("billing_site_engineer", "pmc_bse1"),
        ("qaqc_site_engineer", "pmc_qaqc1"),
        ("hse_site_engineer", "pmc_hse1"),
        ("team_lead", "pmc_tl1"),
    ]:
        u = User.objects.filter(username=uname).first()
        if u and getattr(rgsl, f"{field}_id") == u.id:
            setattr(rgsl, field, None)
            cleared = True
    if cleared:
        rgsl.save(
            update_fields=[
                "team_lead",
                "site_engineer",
                "billing_site_engineer",
                "qaqc_site_engineer",
                "hse_site_engineer",
                "updated_at",
            ]
        )
        print("Cleared *1 users from RGSL")

    # Restore engineer *1 to original project if missing
    if orig:
        for field, uname in [
            ("site_engineer", "pmc_se1"),
            ("billing_site_engineer", "pmc_bse1"),
            ("qaqc_site_engineer", "pmc_qaqc1"),
            ("hse_site_engineer", "pmc_hse1"),
        ]:
            u = User.objects.filter(username=uname).first()
            if u and getattr(orig, f"{field}_id") is None:
                setattr(orig, field, u)
                if field == "site_engineer":
                    orig.site_engineers.add(u)
        orig.save(
            update_fields=[
                "site_engineer",
                "billing_site_engineer",
                "qaqc_site_engineer",
                "hse_site_engineer",
                "updated_at",
            ]
        )
        print(f"Restored engineers *1 on {orig.name}")

rgsl.status = "active"
ROLE_SPECS = {
    "tl": {
        "username": f"pmc_tl{index}",
        "group": "Team Leader",
        "designation": "PMC Team Leader",
        "profile_type": None,
        "password": f"tl@{index}",
        "field": "team_lead",
        "m2m": False,
    },
    "se": {
        "username": f"pmc_se{index}",
        "group": "Site Engineer",
        "designation": "Site Engineer",
        "profile_type": "site_engineer",
        "password": f"Pmc@SE{index}",
        "field": "site_engineer",
        "m2m": True,
    },
    "bse": {
        "username": f"pmc_bse{index}",
        "group": "Billing Site Engineer",
        "designation": "Billing Site Engineer",
        "profile_type": "billing_site_engineer",
        "password": f"Pmc@BSE{index}",
        "field": "billing_site_engineer",
        "m2m": False,
    },
    "qaqc": {
        "username": f"pmc_qaqc{index}",
        "group": "QAQC Site Engineer",
        "designation": "QA/QC Site Engineer",
        "profile_type": "qaqc_site_engineer",
        "password": f"Pmc@QA{index}",
        "field": "qaqc_site_engineer",
        "m2m": False,
    },
    "hse": {
        "username": f"pmc_hse{index}",
        "group": "HSE Site Engineer",
        "designation": "HSE Site Engineer",
        "profile_type": "hse_site_engineer",
        "password": f"Pmc@HSE{index}",
        "field": "hse_site_engineer",
        "m2m": False,
    },
}

print("PROJECT", rgsl.id, rgsl.name, rgsl.status)
for role, spec in ROLE_SPECS.items():
    group, _ = Group.objects.get_or_create(name=spec["group"])
    user, created = User.objects.get_or_create(
        username=spec["username"], defaults={"is_active": True}
    )
    user.is_active = True
    user.set_password(spec["password"])
    user.save()
    user.groups.clear()
    user.groups.add(group)
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.designation = spec["designation"]
    uf = ["designation", "updated_at"]
    if spec["profile_type"]:
        profile.site_engineer_type = spec["profile_type"]
        uf.append("site_engineer_type")
    profile.save(update_fields=uf)
    setattr(rgsl, spec["field"], user)
    if spec["m2m"]:
        rgsl.site_engineers.add(user)
    ok = authenticate(username=spec["username"], password=spec["password"]) is not None
    print(
        f"{role.upper()}|{spec['username']}|{spec['password']}|{user.id}|"
        f"{'new' if created else 'updated'}|{'OK' if ok else 'FAIL'}"
    )

rgsl.save(
    update_fields=[
        "status",
        "team_lead",
        "site_engineer",
        "billing_site_engineer",
        "qaqc_site_engineer",
        "hse_site_engineer",
        "updated_at",
    ]
)
print("DONE")
