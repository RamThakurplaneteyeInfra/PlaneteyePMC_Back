"""
Project-scoped RBAC for the PMC backend.

Enforces:
  - Users only access projects they are assigned to (unless admin role).
  - Write operations require the correct role for the data domain.
"""

from __future__ import annotations

from django.db.models import Q, QuerySet

from projects.models import Project

# ---------------------------------------------------------------------------
# Role constants
# ---------------------------------------------------------------------------

ROLE_CEO = "CEO"
ROLE_PMC_HEAD = "PMC Head"
ROLE_COORDINATOR = "Coordinator"
ROLE_TEAM_LEADER = "Team Leader"
ROLE_SITE_ENGINEER = "Site Engineer"
ROLE_BILLING_SITE_ENGINEER = "Billing Site Engineer"
ROLE_QAQC_SITE_ENGINEER = "QAQC Site Engineer"

ADMIN_ROLES = {ROLE_CEO, ROLE_PMC_HEAD, ROLE_COORDINATOR}

SITE_ENGINEER_ROLES = {
    ROLE_SITE_ENGINEER,
    ROLE_BILLING_SITE_ENGINEER,
    ROLE_QAQC_SITE_ENGINEER,
}

ALL_PROJECT_ROLES = ADMIN_ROLES | SITE_ENGINEER_ROLES | {ROLE_TEAM_LEADER}


# ---------------------------------------------------------------------------
# Data domains (what kind of record is being modified)
# ---------------------------------------------------------------------------

class RBACDomain:
    GENERAL = "general"          # Team Leader full project management
    ENGINEERING = "engineering"    # DPR, progress, site images, scope
    BILLING = "billing"          # contracts, invoicing, cashflow
    FINANCIAL = "financial"      # cost/budget performance, contract values
    QAQC = "qaqc"                # quality status, health & safety, inspections


# Roles allowed to WRITE per domain
WRITE_ROLES_BY_DOMAIN: dict[str, set[str]] = {
    RBACDomain.GENERAL: ADMIN_ROLES | {ROLE_TEAM_LEADER},
    RBACDomain.ENGINEERING: ADMIN_ROLES | {ROLE_TEAM_LEADER, ROLE_SITE_ENGINEER},
    RBACDomain.BILLING: ADMIN_ROLES | {ROLE_TEAM_LEADER, ROLE_BILLING_SITE_ENGINEER},
    RBACDomain.FINANCIAL: ADMIN_ROLES | {ROLE_TEAM_LEADER, ROLE_BILLING_SITE_ENGINEER},
    RBACDomain.QAQC: ADMIN_ROLES | {ROLE_TEAM_LEADER, ROLE_QAQC_SITE_ENGINEER},
}

# Roles allowed to READ per domain (assigned to project + role in set)
READ_ROLES_BY_DOMAIN: dict[str, set[str]] = {
    RBACDomain.GENERAL: ALL_PROJECT_ROLES,
    RBACDomain.ENGINEERING: ALL_PROJECT_ROLES,
    RBACDomain.BILLING: ALL_PROJECT_ROLES,
    RBACDomain.FINANCIAL: ALL_PROJECT_ROLES,
    RBACDomain.QAQC: ALL_PROJECT_ROLES,
}


def _user_role_names(user) -> set[str]:
    if not user or not user.is_authenticated:
        return set()
    if user.is_superuser:
        return ALL_PROJECT_ROLES | {"superuser"}
    return set(user.groups.values_list("name", flat=True))


def is_admin_user(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return bool(_user_role_names(user) & ADMIN_ROLES)


def get_user_assigned_projects_qs(user) -> QuerySet:
    """Projects the user may access."""
    if not user or not user.is_authenticated:
        return Project.objects.none()
    if is_admin_user(user):
        return Project.objects.all()

    return Project.objects.filter(
        Q(team_lead=user)
        | Q(site_engineer=user)
        | Q(site_engineers=user)
        | Q(billing_site_engineer=user)
        | Q(qaqc_site_engineer=user)
        | Q(coordinators=user)
        | Q(pmc_head=user)
        | Q(assigned_users=user)
    ).distinct()


def get_user_assigned_project_ids(user) -> set[int]:
    return set(get_user_assigned_projects_qs(user).values_list("id", flat=True))


def get_user_assigned_project_names(user) -> set[str]:
    return set(get_user_assigned_projects_qs(user).values_list("name", flat=True))


def resolve_project(name: str | None) -> Project | None:
    if not name or not str(name).strip():
        return None
    name = str(name).strip()
    project = Project.objects.filter(name=name).first()
    if project:
        return project
    return Project.objects.filter(name__iexact=name).first()


def user_has_project_access(user, project: Project | None) -> bool:
    if project is None:
        return False
    if is_admin_user(user):
        return True
    return get_user_assigned_projects_qs(user).filter(pk=project.pk).exists()


def user_has_project_name_access(user, project_name: str | None) -> bool:
    project = resolve_project(project_name)
    if project is None:
        return is_admin_user(user)
    return user_has_project_access(user, project)


def user_can_read_domain(user, project: Project | None, domain: str) -> bool:
    if not user_has_project_access(user, project):
        return False
    if is_admin_user(user):
        return True
    roles = _user_role_names(user)
    allowed = READ_ROLES_BY_DOMAIN.get(domain, ALL_PROJECT_ROLES)
    return bool(roles & allowed)


def user_can_write_domain(user, project: Project | None, domain: str) -> bool:
    if not user_has_project_access(user, project):
        return False
    if is_admin_user(user):
        return True
    roles = _user_role_names(user)
    allowed = WRITE_ROLES_BY_DOMAIN.get(domain, set())
    return bool(roles & allowed)


def filter_queryset_by_project_access(
    queryset: QuerySet,
    user,
    project_name_field: str = "project_name",
) -> QuerySet:
    """Filter a queryset to rows belonging to the user's assigned projects."""
    if is_admin_user(user):
        return queryset

    names = get_user_assigned_project_names(user)
    if not names:
        return queryset.none()

    if project_name_field == "project":
        return queryset.filter(project_id__in=get_user_assigned_project_ids(user))

    if project_name_field == "project__name":
        return queryset.filter(project__name__in=names)

    # Case-insensitive match for string project_name fields
    q = Q()
    for name in names:
        q |= Q(**{f"{project_name_field}__iexact": name})
    return queryset.filter(q)


def project_from_instance(obj) -> Project | None:
    """Resolve Project from a model instance."""
    if obj is None:
        return None
    if isinstance(obj, Project):
        return obj
    if hasattr(obj, "project_id") and obj.project_id:
        return obj.project
    if hasattr(obj, "projectName"):
        return resolve_project(getattr(obj, "projectName", None))
    if hasattr(obj, "project_name"):
        return resolve_project(getattr(obj, "project_name", None))
    return None


def extract_project_name_from_data(data) -> str | None:
    if not data:
        return None
    if hasattr(data, "get"):
        name = data.get("project_name") or data.get("projectName")
        if name:
            return str(name).strip()
    return None
