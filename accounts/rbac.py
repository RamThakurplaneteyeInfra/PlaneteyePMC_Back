"""
Project-scoped RBAC for the PMC backend.

Enforces:
  - Users only access projects they are assigned to (unless admin role).
  - Write operations require the correct role for the data domain.
"""

from __future__ import annotations

from urllib.parse import unquote

from django.db.models import QuerySet

from projects.models import Project

# ---------------------------------------------------------------------------
# Role constants
# ---------------------------------------------------------------------------

ROLE_CEO = "CEO"
ROLE_PMC_HEAD = "PMC Head"
ROLE_HEAD_OFFICE = "Head Office"
ROLE_HO_ALIAS = "HO"  # short name — treated as Head Office
ROLE_PMC_MANAGER = "PMC Manager"
ROLE_COORDINATOR = "Coordinator"  # legacy alias — treated as PMC Manager
ROLE_TEAM_LEADER = "Team Leader"
ROLE_TEAM_LEAD_ALIAS = "Team Lead"
ROLE_SITE_ENGINEER = "Site Engineer"
ROLE_BILLING_SITE_ENGINEER = "Billing Site Engineer"
ROLE_QAQC_SITE_ENGINEER = "QAQC Site Engineer"
ROLE_HSE_SITE_ENGINEER = "HSE Site Engineer"

# Organization-wide roles: all projects, all domain writes via WRITE_ROLES_BY_DOMAIN.
ADMIN_ROLES = {
    ROLE_CEO,
    ROLE_PMC_HEAD,
    ROLE_HEAD_OFFICE,
    ROLE_HO_ALIAS,
    ROLE_PMC_MANAGER,
    ROLE_COORDINATOR,
}

SITE_ENGINEER_ROLES = {
    ROLE_SITE_ENGINEER,
    ROLE_BILLING_SITE_ENGINEER,
    ROLE_QAQC_SITE_ENGINEER,
    ROLE_HSE_SITE_ENGINEER,
}

# Roles that HO/Admin may create and manage via User Management APIs.
MANAGEABLE_PROJECT_ROLES = {
    ROLE_TEAM_LEADER,
    ROLE_SITE_ENGINEER,
    ROLE_BILLING_SITE_ENGINEER,
    ROLE_QAQC_SITE_ENGINEER,
    ROLE_HSE_SITE_ENGINEER,
}

# Who may access User Management (HO + organizational Admin).
# PMC Manager / Coordinator remain data admins but not user administrators.
USER_MANAGEMENT_ROLES = {
    ROLE_CEO,
    ROLE_PMC_HEAD,
    ROLE_HEAD_OFFICE,
    ROLE_HO_ALIAS,
}

ALL_PROJECT_ROLES = ADMIN_ROLES | SITE_ENGINEER_ROLES | {ROLE_TEAM_LEADER, ROLE_TEAM_LEAD_ALIAS}

# Frontend / legacy spellings → canonical Project.name in DB.
# Keys must be lowercase; values are the exact DB names.
PROJECT_NAME_ALIASES: dict[str, str] = {
    "mayapur flyover": "Miyapur Flyover",
}


def normalize_project_name(name: str | None) -> str:
    """Decode URL-encoded names, collapse whitespace, and apply known aliases."""
    if not name:
        return ""
    cleaned = " ".join(unquote(str(name)).strip().split())
    return PROJECT_NAME_ALIASES.get(cleaned.lower(), cleaned)


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
    cached = getattr(user, "_rbac_role_names", None)
    if cached is not None:
        return cached
    if user.is_superuser:
        roles = ALL_PROJECT_ROLES | {"superuser"}
        user._rbac_role_names = roles
        return roles
    roles = set(user.groups.values_list("name", flat=True))
    if ROLE_TEAM_LEAD_ALIAS in roles:
        roles.add(ROLE_TEAM_LEADER)
    # Normalize short / legacy aliases into canonical admin role names.
    if ROLE_HO_ALIAS in roles:
        roles.add(ROLE_HEAD_OFFICE)
    if ROLE_HEAD_OFFICE in roles:
        roles.add(ROLE_HO_ALIAS)
    if ROLE_COORDINATOR in roles:
        roles.add(ROLE_PMC_MANAGER)
    try:
        profile = user.profile
        if profile.designation in (ROLE_TEAM_LEADER, ROLE_TEAM_LEAD_ALIAS, "PMC Team Leader"):
            roles.add(ROLE_TEAM_LEADER)
        if profile.designation in (ROLE_HEAD_OFFICE, ROLE_HO_ALIAS, "Head Office (HO)"):
            roles.add(ROLE_HEAD_OFFICE)
            roles.add(ROLE_HO_ALIAS)
    except Exception:
        pass
    user._rbac_role_names = roles
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


def can_manage_users(user) -> bool:
    """
    True when the user may use User Management APIs
    (create TL/engineers, assign projects, reset passwords, etc.).
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return bool(_user_role_names(user) & USER_MANAGEMENT_ROLES)


def is_manageable_project_role(role_name: str | None) -> bool:
    """True for Team Leader / Site Engineer family roles HO may create."""
    if not role_name:
        return False
    name = str(role_name).strip()
    if name == ROLE_TEAM_LEAD_ALIAS:
        name = ROLE_TEAM_LEADER
    return name in MANAGEABLE_PROJECT_ROLES


def _load_assigned_projects(user) -> None:
    """
    Load assigned project id/name sets once per request (non-admin only).

    Uses separate index lookups instead of one OR+DISTINCT across M2M joins,
    which explodes on large project tables.
    """
    if getattr(user, "_rbac_assigned_loaded", False):
        return
    id_querysets = (
        Project.objects.filter(team_lead=user).values_list("id", flat=True),
        Project.objects.filter(site_engineer=user).values_list("id", flat=True),
        Project.objects.filter(billing_site_engineer=user).values_list("id", flat=True),
        Project.objects.filter(qaqc_site_engineer=user).values_list("id", flat=True),
        Project.objects.filter(hse_site_engineer=user).values_list("id", flat=True),
        Project.objects.filter(pmc_head=user).values_list("id", flat=True),
        Project.objects.filter(site_engineers=user).values_list("id", flat=True),
        Project.objects.filter(coordinators=user).values_list("id", flat=True),
        Project.objects.filter(assigned_users=user).values_list("id", flat=True),
    )
    ids: set[int] = set()
    for qs in id_querysets:
        ids.update(qs)
    if ids:
        rows = list(
            Project.objects.filter(pk__in=ids).values_list("id", "name")
        )
    else:
        rows = []
    user._rbac_assigned_project_ids = {row[0] for row in rows}
    user._rbac_assigned_project_names = {row[1] for row in rows if row[1]}
    user._rbac_assigned_loaded = True


def get_user_assigned_projects_qs(user) -> QuerySet:
    """Projects the user may access."""
    if not user or not user.is_authenticated:
        return Project.objects.none()
    if is_admin_user(user):
        return Project.objects.all()
    _load_assigned_projects(user)
    return Project.objects.filter(pk__in=user._rbac_assigned_project_ids)


def get_user_assigned_project_ids(user) -> set[int]:
    if not user or not user.is_authenticated:
        return set()
    if is_admin_user(user):
        cached = getattr(user, "_rbac_admin_project_ids", None)
        if cached is None:
            cached = set(Project.objects.values_list("id", flat=True))
            user._rbac_admin_project_ids = cached
        return cached
    _load_assigned_projects(user)
    return set(user._rbac_assigned_project_ids)


def get_user_assigned_project_names(user) -> set[str]:
    if not user or not user.is_authenticated:
        return set()
    if is_admin_user(user):
        cached = getattr(user, "_rbac_admin_project_names", None)
        if cached is None:
            cached = set(
                Project.objects.exclude(name="").values_list("name", flat=True)
            )
            user._rbac_admin_project_names = cached
        return cached
    _load_assigned_projects(user)
    return set(user._rbac_assigned_project_names)


def resolve_project(name: str | None, user=None) -> Project | None:
    """
    Resolve a Project by name.

    When *user* is provided, prefer a project that user is assigned to
    (case-insensitive). This avoids false denials when duplicate project
    rows exist that differ only by casing (e.g. "Khb …" vs "KHB …").

    Results are memoized on *user* for the lifetime of the request so
    permission + object checks do not repeat the same Project SELECT.
    """
    name = normalize_project_name(name)
    if not name:
        return None

    cache_map = None
    if user is not None and getattr(user, "is_authenticated", False):
        cache_map = getattr(user, "_rbac_resolve_project_cache", None)
        if cache_map is None:
            cache_map = {}
            user._rbac_resolve_project_cache = cache_map
        if name in cache_map:
            return cache_map[name]

    project = None
    if user is not None and getattr(user, "is_authenticated", False) and not is_admin_user(user):
        assigned = (
            get_user_assigned_projects_qs(user)
            .filter(name__iexact=name)
            .order_by("id")
            .first()
        )
        if assigned is not None:
            project = assigned

    if project is None:
        project = Project.objects.filter(name=name).first()
    if project is None:
        matches = list(Project.objects.filter(name__iexact=name).order_by("id"))
        if not matches:
            project = None
        elif len(matches) == 1:
            project = matches[0]
        else:
            project = None
            for candidate in matches:
                if (
                    candidate.team_lead_id
                    or candidate.billing_site_engineer_id
                    or candidate.pmc_head_id
                    or candidate.site_engineer_id
                    or candidate.qaqc_site_engineer_id
                    or getattr(candidate, "hse_site_engineer_id", None)
                ):
                    project = candidate
                    break
            if project is None:
                project = matches[0]

    if cache_map is not None:
        cache_map[name] = project
    return project


def user_has_project_access(user, project: Project | None) -> bool:
    if project is None:
        return False
    if is_admin_user(user):
        return True
    return project.pk in get_user_assigned_project_ids(user)


def user_has_project_name_access(user, project_name: str | None) -> bool:
    if not project_name:
        return is_admin_user(user)
    project = resolve_project(project_name, user=user)
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


def _instance_project_name(obj) -> str | None:
    """Support both camelCase projectName and snake_case project_name fields."""
    if obj is None:
        return None
    for attr in ("project_name", "projectName"):
        value = getattr(obj, attr, None)
        if value:
            return str(value).strip()
    return None


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

    raw_name = _instance_project_name(obj)
    name_project = resolve_project(raw_name) if raw_name else None

    fk_project = None
    if getattr(obj, "project_id", None):
        fk_project = obj.project

    if user is not None:
        if name_project and user_has_project_access(user, name_project):
            return name_project
        if fk_project and user_has_project_access(user, fk_project):
            return fk_project
        if raw_name:
            assigned = (
                get_user_assigned_projects_qs(user)
                .filter(name__iexact=normalize_project_name(raw_name))
                .first()
            )
            if assigned is not None:
                return assigned
        # Admins may still resolve via name/FK even when not "assigned"
        if is_admin_user(user):
            return name_project or fk_project
        return None

    return name_project or fk_project


def project_from_instance(obj, user=None) -> Project | None:
    """Resolve Project from a model instance."""
    raw_name = _instance_project_name(obj)
    if raw_name:
        resolved = resolve_project(raw_name, user=user)
        if resolved:
            return resolved
    return resolve_project_for_instance(obj, user=user)


def extract_project_name_from_data(data) -> str | None:
    if not data:
        return None
    if hasattr(data, "get"):
        name = data.get("project_name") or data.get("projectName")
        if name:
            return str(name).strip()
    return None
