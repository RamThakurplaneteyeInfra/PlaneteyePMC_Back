from rest_framework.permissions import SAFE_METHODS, BasePermission

from accounts.rbac import is_admin_user, user_has_project_access

CREATE_ROLES = {"Team Leader", "PMC Head"}
DELETE_ROLES = {"Team Leader", "PMC Head"}


def role_names(user) -> set[str]:
    if not user or not user.is_authenticated:
        return set()
    if user.is_superuser:
        return {"superuser", "PMC Head", "Team Leader"}
    return set(user.groups.values_list("name", flat=True))


def is_pmc_head(user) -> bool:
    return "PMC Head" in role_names(user)


def can_create_feedback(user, project) -> bool:
    """Team Leader / PMC Head / Admin. Site Engineers cannot create."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff or is_admin_user(user):
        return True
    roles = role_names(user)
    if not roles & CREATE_ROLES:
        return False
    if "PMC Head" in roles:
        return True
    return user_has_project_access(user, project)


def can_read_feedback(user, project) -> bool:
    """Any assigned project member (incl. Site Engineer) + admin/PMC Head."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff or is_admin_user(user):
        return True
    return user_has_project_access(user, project)


def can_update_feedback(user, feedback) -> bool:
    """Team Leader on the project, PMC Head, reporter (if TL), or admin."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff or is_admin_user(user):
        return True
    roles = role_names(user)
    if "PMC Head" in roles:
        return True
    if "Team Leader" in roles and user_has_project_access(user, feedback.project):
        return True
    if feedback.reported_by_id and feedback.reported_by_id == user.id:
        return user_has_project_access(user, feedback.project)
    return False


def can_delete_feedback(user, project) -> bool:
    """Team Leader (assigned project) / PMC Head / Admin."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff or is_admin_user(user):
        return True
    roles = role_names(user)
    if "PMC Head" in roles:
        return True
    if "Team Leader" in roles:
        return user_has_project_access(user, project)
    return False


def can_change_status(user, feedback) -> bool:
    """Status/priority workflow changes: PMC Head, Team Leader (project), Admin."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff or is_admin_user(user):
        return True
    roles = role_names(user)
    if "PMC Head" in roles:
        return True
    if "Team Leader" in roles and user_has_project_access(user, feedback.project):
        return True
    return False


class FeedbackPermission(BasePermission):
    message = "You do not have permission to manage project feedback."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return can_read_feedback(request.user, obj.project)
        if request.method == "DELETE":
            return can_delete_feedback(request.user, obj.project)
        return can_update_feedback(request.user, obj)
