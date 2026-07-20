from rest_framework.permissions import SAFE_METHODS, BasePermission

from accounts.rbac import is_admin_user, user_has_project_access

CREATE_ROLES = {"QAQC Site Engineer", "Team Leader", "PMC Head"}
DELETE_ROLES = {"Team Leader", "PMC Head"}
# Update: uploader OR Team Leader / PMC Head / Admin (checked in helpers)


def role_names(user) -> set[str]:
    if not user or not user.is_authenticated:
        return set()
    if user.is_superuser:
        return {"superuser", "PMC Head", "Team Leader", "QAQC Site Engineer"}
    return set(user.groups.values_list("name", flat=True))


def can_create_testing_document(user, project) -> bool:
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


def can_read_testing_document(user, project) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff or is_admin_user(user):
        return True
    return user_has_project_access(user, project)


def can_update_testing_document(user, document) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff or is_admin_user(user):
        return True
    roles = role_names(user)
    if "PMC Head" in roles:
        return True
    if "Team Leader" in roles and user_has_project_access(user, document.project):
        return True
    if document.uploaded_by_id and document.uploaded_by_id == user.id:
        return user_has_project_access(user, document.project)
    return False


def can_delete_testing_document(user, project) -> bool:
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


class TestingDocumentPermission(BasePermission):
    message = "You do not have permission to manage testing documents."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return can_read_testing_document(request.user, obj.project)
        if request.method == "DELETE":
            return can_delete_testing_document(request.user, obj.project)
        return can_update_testing_document(request.user, obj)
