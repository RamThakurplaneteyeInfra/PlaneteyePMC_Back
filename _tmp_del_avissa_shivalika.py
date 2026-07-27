from django.contrib.auth import get_user_model
from django.db import transaction

from contractors.models import Contractor
from project_dates.models import ProjectDates
from projects.models import Project
from projects.pmc_team_mappings import TL_PROJECT_MAPPINGS

User = get_user_model()

NAMES = ["AVISSA", "SHIVALIKA"]


def find_projects(name: str):
    qs = Project.objects.filter(name__iexact=name) | Project.objects.filter(name__icontains=name)
    return list(qs.distinct().order_by("id"))


def delete_project(project: Project) -> None:
    pid = project.id
    print(f"Removing id={pid} name={project.name!r} status={project.status} TL={getattr(project.team_lead, 'username', None)}")
    pd_count, _ = ProjectDates.objects.filter(project_id=pid).delete()
    print(f"  ProjectDates deleted: {pd_count}")
    c_count, _ = Contractor.objects.filter(project_id=pid).delete()
    print(f"  Contractors deleted: {c_count}")
    project.site_engineers.clear()
    project.coordinators.clear()
    try:
        project.assigned_users.clear()
    except Exception:
        pass
    try:
        project.delete()
        print(f"  DELETED id={pid}")
    except Exception as exc:
        print(f"  HARD_DELETE_FAILED: {type(exc).__name__}: {exc}")
        # Soft-clear as fallback
        project.status = "on_hold"
        project.team_lead = None
        project.site_engineer = None
        project.billing_site_engineer = None
        project.qaqc_site_engineer = None
        project.hse_site_engineer = None
        project.save(
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
        print(f"  SOFT_CLEARED id={pid}")


with transaction.atomic():
    for name in NAMES:
        found = find_projects(name)
        if not found:
            print(f"NOT_FOUND {name!r}")
            continue
        for p in found:
            # Only exact AVISSA / SHIVALIKA, not "Avissa G+40" or "Shivalik Building..."
            if p.name.strip().upper() in {"AVISSA", "SHIVALIKA"}:
                delete_project(p)
            else:
                print(f"SKIP similar name id={p.id} {p.name!r}")

print("--- after ---")
for name in NAMES:
    print(name, list(Project.objects.filter(name__iexact=name).values_list("id", "name")))

print("mappings still containing AVISSA/SHIVALIKA:")
for tl, pname in TL_PROJECT_MAPPINGS:
    if "AVISSA" in pname.upper() or "SHIVALIKA" in pname.upper() or "SHIVALIK" in pname.upper():
        print(" ", tl, pname)
