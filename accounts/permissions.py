"""DRF permission classes for project-scoped RBAC."""

from rest_framework.permissions import BasePermission, SAFE_METHODS

from .rbac import (
    RBACDomain,
    extract_project_name_from_data,
    normalize_project_name,
    project_from_instance,
    resolve_project,
    resolve_project_for_instance,
    user_can_manage_contractors,
    user_can_read_domain,
    user_can_write_domain,
    user_has_project_access,
)


class IsAuthenticatedProjectRBAC(BasePermission):
    """
    Object-level project RBAC.

    ViewSet attributes:
      rbac_domain: str (RBACDomain.*) — default GENERAL
      rbac_project_name_field: str — for queryset filtering via mixin
    """

    message = "You do not have permission to perform this action on this project."

    def _get_domain(self, view) -> str:
        return getattr(view, "rbac_domain", RBACDomain.GENERAL)

    def _resolve_project_from_view(self, request, view):
        if hasattr(view, "get_rbac_project"):
            return view.get_rbac_project()

        kwargs = getattr(view, "kwargs", {}) or {}
        project_name = (
            request.query_params.get("project_name")
            or request.query_params.get("projectName")
            or kwargs.get("project_name")
            or kwargs.get("projectName")
            or extract_project_name_from_data(request.data)
        )
        if project_name:
            return resolve_project(normalize_project_name(project_name), user=request.user)

        pk = view.kwargs.get("pk") or view.kwargs.get("project_pk")
        if pk and hasattr(view, "queryset") and view.queryset is not None:
            try:
                obj = view.queryset.model.objects.filter(pk=pk).first()
                user = getattr(request, "user", None)
                if user and user.is_authenticated:
                    project = resolve_project_for_instance(obj, user=user)
                    if project is not None:
                        return project
                return project_from_instance(obj)
            except Exception:
                pass
        return None

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.method in SAFE_METHODS:
            project = self._resolve_project_from_view(request, view)
            if project is None:
                return True
            return user_can_read_domain(request.user, project, self._get_domain(view))

        project = self._resolve_project_from_view(request, view)
        if project is None:
            return True
        if getattr(project, "status", None) == "completed":
            # Skip lock for the dedicated complete action (idempotent already-completed handled in service).
            action = getattr(view, "action", None)
            if action != "complete_project":
                from accounts.rbac_checks import ProjectReadOnlyError

                raise ProjectReadOnlyError()
        return user_can_write_domain(request.user, project, self._get_domain(view))

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False

        project = project_from_instance(obj)
        domain = self._get_domain(view)

        if request.method in SAFE_METHODS:
            return user_can_read_domain(request.user, project, domain)

        if getattr(project, "status", None) == "completed":
            action = getattr(view, "action", None)
            if action != "complete_project":
                from accounts.rbac_checks import ProjectReadOnlyError

                raise ProjectReadOnlyError()
        return user_can_write_domain(request.user, project, domain)


class CanManageProjectContractors(BasePermission):
    """
    Contractor Master permissions.

    - GET: any role with project read access
    - POST/PATCH/DELETE: Team Leader (or admin) on the target project
    """

    message = "You do not have permission to manage contractors for this project."

    def _resolve_project(self, view):
        if hasattr(view, "get_rbac_project"):
            return view.get_rbac_project()
        return None

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        project = self._resolve_project(view)
        if project is None:
            return True

        if request.method in SAFE_METHODS:
            return user_can_read_domain(request.user, project, RBACDomain.GENERAL)

        return user_can_manage_contractors(request.user, project)


class IsTeamLeaderOrAdmin(BasePermission):
    """Team Leader or admin roles only."""

    message = "Only Team Leader or admin roles may perform this action."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        roles = set(request.user.groups.values_list("name", flat=True))
        from .rbac import ADMIN_ROLES, ROLE_TEAM_LEADER

        return ROLE_TEAM_LEADER in roles or bool(roles & ADMIN_ROLES)

    def has_object_permission(self, request, view, obj):
        from .rbac import project_from_instance

        project = project_from_instance(obj)
        if project is None:
            return self.has_permission(request, view)
        return user_has_project_access(request.user, project) and self.has_permission(
            request, view
        )


class CanManageUsers(BasePermission):
    """
    Head Office and organizational Admins (CEO, PMC Head, superuser)
    may manage Team Leaders and Engineers via /api/users/.
    """

    message = "Only Head Office or Admin may manage users."

    def has_permission(self, request, view):
        from .rbac import can_manage_users

        return can_manage_users(getattr(request, "user", None))

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


class CanDeleteSites(BasePermission):
    """
    Site deletion (Init List) — Admin / Head Office / CEO / PMC Head only.

    Reuses ``can_manage_users`` (USER_MANAGEMENT_ROLES + superuser).
    Team Leaders and all Site Engineer roles are denied.
    """

    message = "Only Admin, Head Office, CEO, or PMC Head may delete sites."

    def has_permission(self, request, view):
        from .rbac import can_manage_users

        return can_manage_users(getattr(request, "user", None))

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)
