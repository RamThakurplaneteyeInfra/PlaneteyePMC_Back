"""RBAC for global Tutorial Videos (not project-scoped)."""

from rest_framework.permissions import SAFE_METHODS, BasePermission

from accounts.rbac import (
    ADMIN_ROLES,
    ROLE_PMC_HEAD,
    ROLE_PMC_MANAGER,
    ROLE_SITE_ENGINEER,
    ROLE_TEAM_LEAD_ALIAS,
    ROLE_TEAM_LEADER,
    SITE_ENGINEER_ROLES,
    is_admin_user,
)

# List / detail / playback: PMC Manager, Site Engineers (all types), Team Leader, admins.
VIEW_ROLES = (
    ADMIN_ROLES  # CEO, PMC Head, Head Office, PMC Manager, Coordinator, …
    | SITE_ENGINEER_ROLES  # Site Engineer, Billing / QAQC / HSE Site Engineer
    | {ROLE_TEAM_LEADER, ROLE_TEAM_LEAD_ALIAS, ROLE_PMC_MANAGER, ROLE_SITE_ENGINEER}
)

# Upload / update / delete: PMC Head, Team Leader, and other admin roles (not SE).
MANAGE_ROLES = ADMIN_ROLES | {ROLE_TEAM_LEADER, ROLE_PMC_HEAD, ROLE_TEAM_LEAD_ALIAS}


def role_names(user) -> set[str]:
    if not user or not user.is_authenticated:
        return set()
    if user.is_superuser:
        return set(VIEW_ROLES | MANAGE_ROLES) | {"superuser"}
    return set(user.groups.values_list("name", flat=True))


def can_view_tutorial_videos(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff or is_admin_user(user):
        return True
    return bool(role_names(user) & VIEW_ROLES)


def can_manage_tutorial_videos(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff or is_admin_user(user):
        return True
    return bool(role_names(user) & MANAGE_ROLES)


class TutorialVideoPermission(BasePermission):
    message = "You do not have permission to access tutorial videos."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return can_view_tutorial_videos(request.user)
        return can_manage_tutorial_videos(request.user)

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return can_view_tutorial_videos(request.user)
        return can_manage_tutorial_videos(request.user)
