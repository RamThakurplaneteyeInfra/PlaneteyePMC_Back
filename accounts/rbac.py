"""
Project-scoped RBAC for the PMC backend.

Enforces:
  - Users only access projects they are assigned to (unless admin role).
  - Write operations require the correct role for the data domain.
"""

from __future__ import annotations

from urllib.parse import unquote

from django.db.models import Q, QuerySet

from projects.models import Project

# ---------------------------------------------------------------------------
# Role constants
# ---------------------------------------------------------------------------

ROLE_CEO = "CEO"
ROLE_PMC_HEAD = "PMC Head"
ROLE_COORDINATOR = "Coordinator"
ROLE_TEAM_LEADER = "Team Leader"
ROLE_TEAM_LEAD_ALIAS = "Team Lead"
ROLE_SITE_ENGINEER = "Site Engineer"
ROLE_BILLING_SITE_ENGINEER = "Billing Site Engineer"
ROLE_QAQC_SITE_ENGINEER = "QAQC Site Engineer"
ROLE_HSE_SITE_ENGINEER = "HSE Site Engineer"

ADMIN_ROLES = {ROLE_CEO, ROLE_PMC_HEAD, ROLE_COORDINATOR}

SITE_ENGINEER_ROLES = {
    ROLE_SITE_ENGINEER,
    ROLE_BILLING_SITE_ENGINEER,
    ROLE_QAQC_SITE_ENGINEER,
    ROLE_HSE_SITE_ENGINEER,
}

ALL_PROJECT_ROLES = ADMIN_ROLES | SITE_ENGINEER_ROLES | {ROLE_TEAM_LEADER, ROLE_TEAM_LEAD_ALIAS}


def normalize_project_name(name: str | None) -> str:
    """Decode URL-encoded names and collapse extra whitespace."""
    if not name:
        return ""
    return " ".join(unquote(str(name)).strip().split())


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
    # HSE Site Engineer can write health & safety (same domain as QA/QC).
    RBACDomain.QAQC: ADMIN_ROLES | {
        ROLE_TEAM_LEADER,
        ROLE_QAQC_SITE_ENGINEER,
        ROLE_HSE_SITE_ENGINEER,
    },
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
    roles = set(user.groups.values_list("name", flat=True))
    if ROLE_TEAM_LEAD_ALIAS in roles:
        roles.add(ROLE_TEAM_LEADER)
    try:
        profile = user.profile
        if profile.designation in (ROLE_TEAM_LEADER, ROLE_TEAM_LEAD_ALIAS, "PMC Team Leader"):
            roles.add(ROLE_TEAM_LEADER)
    except Exception:
        pass
    return roles


def user_is_team_leader(user) -> bool:
    return ROLE_TEAM_LEADER in _user_role_names(user)


def is_mapped_team_leader_for_project(user, project: Project | None) -> bool:
    """True when username/project match the canonical PMC TL mapping table."""
    if not user or not project:
        return False
    try:
        from projects.pmc_team_mappings import TL_PROJECT_MAPPINGS
    except ImportError:
        return False

    uname = user.username.strip().lower()
    pname = normalize_project_name(project.name).lower()
    for tl_user, mapped_name in TL_PROJECT_MAPPINGS:
        if tl_user.strip().lower() == uname and normalize_project_name(mapped_name).lower() == pname:
            return True
    return False


def user_can_manage_contractors(user, project: Project | None) -> bool:
    """Team Leaders (and admins) may add/update contractors for their projects."""
    if project is None:
        return False
    if is_admin_user(user):
        return True
    if not user_is_team_leader(user):
        return False
    if project.team_lead_id == user.id:
        return True
    if project.assigned_users.filter(pk=user.pk).exists():
        return True
    if is_mapped_team_leader_for_project(user, project):
        return True
    return user_has_project_access(user, project)


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
        | Q(hse_site_engineer=user)
        | Q(coordinators=user)
        | Q(pmc_head=user)
        | Q(assigned_users=user)
    ).distinct()


def get_user_assigned_project_ids(user) -> set[int]:
    return set(get_user_assigned_projects_qs(user).values_list("id", flat=True))


def get_user_assigned_project_names(user) -> set[str]:
    return set(get_user_assigned_projects_qs(user).values_list("name", flat=True))


def resolve_project(name: str | None) -> Project | None:
    name = normalize_project_name(name)
    if not name:
        return None
    project = Project.objects.filter(name=name).first()
    if project:
        return project
    matches = list(Project.objects.filter(name__iexact=name).order_by("id"))
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    for project in matches:
        if (
            project.team_lead_id
            or project.billing_site_engineer_id
            or project.pmc_head_id
            or project.site_engineer_id
        ):
            return project
    return matches[0]


def user_has_project_access(user, project: Project | None) -> bool:
    if project is None:
        return False
    if is_admin_user(user):
        return True
    return get_user_assigned_projects_qs(user).filter(pk=project.pk).exists()


def user_has_project_name_access(user, project_name: str | None) -> bool:
    if not project_name:
        return is_admin_user(user)
    project = resolve_project(project_name)
    if project is not None and user_has_project_access(user, project):
        return True
    if is_admin_user(user):
        return True
    return (
        get_user_assigned_projects_qs(user)
        .filter(name__iexact=normalize_project_name(project_name))
        .exists()
    )


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

    # Case-insensitive match without building a giant OR of __iexact clauses.
    # Lower(field)__in preserves the same visibility as per-name iexact matching.
    from django.db.models.functions import Lower

    lowered = {str(name).lower() for name in names}
    alias_name = "_rbac_project_name_lower"
    return queryset.alias(**{alias_name: Lower(project_name_field)}).filter(
        **{f"{alias_name}__in": lowered}
    )


def resolve_project_for_instance(obj, user=None) -> Project | None:
    """
    Resolve the project linked to a model instance.

  When *user* is provided, prefer the project_name match the user can access
    (handles legacy rows whose FK points at a duplicate Project row).
    """
    if obj is None:
        return None
    if isinstance(obj, Project):
        return obj

    name_project = None
    if getattr(obj, "project_name", None):
        name_project = resolve_project(obj.project_name)

    fk_project = None
    if getattr(obj, "project_id", None):
        fk_project = obj.project

    if user is not None:
        if name_project and user_has_project_access(user, name_project):
            return name_project
        if fk_project and user_has_project_access(user, fk_project):
            return fk_project
        raw_name = getattr(obj, "project_name", None)
        if raw_name:
            assigned = (
                get_user_assigned_projects_qs(user)
                .filter(name__iexact=normalize_project_name(raw_name))
                .first()
            )
            if assigned is not None:
                return assigned
        return None

    return name_project or fk_project


def project_from_instance(obj) -> Project | None:
    """Resolve Project from a model instance."""
    if hasattr(obj, "projectName"):
        resolved = resolve_project(getattr(obj, "projectName", None))
        if resolved:
            return resolved
    return resolve_project_for_instance(obj)


def extract_project_name_from_data(data) -> str | None:
    if not data:
        return None
    if hasattr(data, "get"):
        name = data.get("project_name") or data.get("projectName")
        if name:
            return str(name).strip()
    return None
