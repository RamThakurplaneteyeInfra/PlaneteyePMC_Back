from rest_framework.permissions import BasePermission, SAFE_METHODS

from accounts.rbac import get_user_assigned_projects_qs, is_admin_user, user_has_project_access


UPLOAD_ROLES = {"PMC Head", "Team Leader", "Site Engineer"}
DELETE_ROLES = {"PMC Head", "Team Leader"}


def role_names(user) -> set[str]:
    if not user or not user.is_authenticated:
        return set()
    if user.is_superuser:
        return {"superuser", "PMC Head", "Team Leader", "Site Engineer"}
    return set(user.groups.values_list("name", flat=True))


def can_upload_meeting_document(user, project) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    roles = role_names(user)
    if not roles & UPLOAD_ROLES:
        return False
    if "PMC Head" in roles:
        return True
    return user_has_project_access(user, project)


def can_delete_meeting_document(user, project) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    roles = role_names(user)
    if "PMC Head" in roles:
        return True
    if "Team Leader" in roles:
        return user_has_project_access(user, project)
    return False


class MeetingDocumentPermission(BasePermission):
    message = "You do not have permission to manage meeting documents."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return is_admin_user(request.user) or user_has_project_access(
                request.user,
                obj.project,
            )
        if request.method == "DELETE":
            return can_delete_meeting_document(request.user, obj.project)
        return can_upload_meeting_document(request.user, obj.project)
