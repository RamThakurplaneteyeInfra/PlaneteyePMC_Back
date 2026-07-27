"""Raise PermissionDenied when RBAC rules block an action."""

from rest_framework.exceptions import PermissionDenied

from .rbac import (
    RBACDomain,
    normalize_project_name,
    project_from_instance,
    resolve_project,
    resolve_project_for_instance,
    get_user_assigned_projects_qs,
    user_can_manage_contractors,
    user_can_write_domain,
    user_has_project_access,
    user_has_project_name_access,
    filter_queryset_by_project_access,
)
from .utils import get_user_role


def apply_project_rbac_to_queryset(queryset, request, project_name_field="project_name"):
    """Filter queryset to projects the user is assigned to (admins see all)."""
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        return filter_queryset_by_project_access(queryset, user, project_name_field)
    return queryset


def enforce_project_access(user, project, *, message: str | None = None) -> None:
    if not user_has_project_access(user, project):
        raise PermissionDenied(message or "You do not have access to this project.")


def enforce_project_access_by_name(
    user,
    project_name: str | None,
    *,
    message: str | None = None,
) -> None:
    if not user_has_project_name_access(user, project_name):
        raise PermissionDenied(
            message or "You do not have access to this project."
        )


def enforce_project_write(
    user,
    project,
    domain: str = RBACDomain.GENERAL,
    *,
    message: str | None = None,
) -> None:
    enforce_project_access(user, project)
    if not user_can_write_domain(user, project, domain):
        raise PermissionDenied(
            message
            or f"You do not have permission to modify {domain} data for this project."
        )


def enforce_project_write_by_name(
    user,
    project_name: str | None,
    domain: str = RBACDomain.GENERAL,
) -> None:
    project = resolve_project(project_name, user=user)
    if project is None or not user_has_project_access(user, project):
        assigned = None
        if project_name:
            assigned = (
                get_user_assigned_projects_qs(user)
                .filter(name__iexact=normalize_project_name(project_name))
                .first()
            )
        if assigned is None:
            raise PermissionDenied("Project not found or access denied.")
        project = assigned
    enforce_project_write(user, project, domain)


def enforce_instance_write(user, instance, domain: str = RBACDomain.GENERAL) -> None:
    project = resolve_project_for_instance(instance, user=user)
    if project is None:
        project_name = None
        for attr in ("project_name", "projectName"):
            value = getattr(instance, attr, None)
            if value:
                project_name = str(value).strip()
                break
        if project_name:
            enforce_project_write_by_name(user, project_name, domain)
            return
        raise PermissionDenied("You do not have access to this project.")
    enforce_project_write(user, project, domain)


def enforce_contractor_manage(user, project) -> None:
    """Raise PermissionDenied unless the user may manage contractors on this project."""
    if not user_can_manage_contractors(user, project):
        raise PermissionDenied(
            "You do not have permission to manage contractors for this project."
        )


def site_engineer_cannot_delete_approved_dpr(user, instance) -> None:
    """Site Engineer may not delete approved DPR records."""
    if get_user_role(user) != "Site Engineer":
        return
    status_value = getattr(instance, "status", None)
    if status_value in ("approved", "APPROVED"):
        raise PermissionDenied("Site Engineers cannot delete approved DPR records.")
