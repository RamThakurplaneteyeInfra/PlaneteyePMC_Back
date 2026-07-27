from django.apps import apps
from django.db import transaction

from contractors.models import Contractor
from project_dates.models import ProjectDates
from projects.models import Project

PROJECT_NAME = "SHIVALIKA"

with transaction.atomic():
    project = Project.objects.filter(name=PROJECT_NAME, team_lead__username="pmc_tl25").first()
    if project is None:
        project = Project.objects.filter(name__iexact=PROJECT_NAME).first()
    if project is None:
        print("NOT_FOUND")
    else:
        pid = project.id
        print(f"Removing project id={pid} name={project.name!r}")

        # Break PROTECT: ProjectDates.contractor -> Contractor
        pd_count, _ = ProjectDates.objects.filter(project_id=pid).delete()
        print(f"Deleted ProjectDates: {pd_count}")

        # Delete known CASCADE children that might still block via PROTECT elsewhere
        c_count, _ = Contractor.objects.filter(project_id=pid).delete()
        print(f"Deleted Contractors: {c_count}")

        project.site_engineers.clear()
        project.coordinators.clear()

        # Collect remaining related objects that reference this project
        # and delete PROTECT-linked rows if any remain.
        try:
            project.delete()
            print(f"DELETED project id={pid}")
        except Exception as exc:
            print(f"DELETE_FAILED: {type(exc).__name__}: {exc}")
            # Fallback soft-remove if hard delete still blocked
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
            print("SOFT_CLEARED team and set on_hold instead")

print("exists_after", Project.objects.filter(name__iexact=PROJECT_NAME).exists())
from django.contrib.auth import get_user_model

U = get_user_model()
tl = U.objects.filter(username="pmc_tl25").first()
print("tl25_leads", list(tl.lead_projects.values_list("id", "name")) if tl else None)
