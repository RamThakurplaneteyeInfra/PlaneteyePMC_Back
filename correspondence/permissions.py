from rest_framework.permissions import BasePermission, SAFE_METHODS

from accounts.rbac import is_admin_user, resolve_project, user_has_project_access


UPLOAD_ROLES = {
    "PMC Head",
    "Team Leader",
    "Site Engineer",
    "Billing Site Engineer",
}
DELETE_ROLES = {"PMC Head", "Team Leader"}


def role_names(user) -> set[str]:
    if not user or not user.is_authenticated:
        return set()
    if user.is_superuser:
        return {"superuser", "PMC Head", "Team Leader", "Site Engineer", "Billing Site Engineer"}
    return set(user.groups.values_list("name", flat=True))


def _project_for_correspondence(correspondence):
    return resolve_project(correspondence.project_name)


def can_upload_correspondence_attachment(user, correspondence) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    roles = role_names(user)
    if not roles & UPLOAD_ROLES:
        return False
    if "PMC Head" in roles:
        return True
    project = _project_for_correspondence(correspondence)
    if project is None:
        return False
    return user_has_project_access(user, project)


def can_view_correspondence_attachment(user, correspondence) -> bool:
    if not user or not user.is_authenticated:
        return False
    if is_admin_user(user):
        return True
    project = _project_for_correspondence(correspondence)
    if project is None:
        return True
    return user_has_project_access(user, project)


def can_delete_correspondence_attachment(user, attachment) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    roles = role_names(user)
    if "PMC Head" in roles:
        return True
    if attachment.uploaded_by_id == user.id:
        return True
    project = attachment.project
    if "Team Leader" in roles and user_has_project_access(user, project):
        return True
    return False


class CorrespondenceAttachmentPermission(BasePermission):
    message = "You do not have permission to manage correspondence attachments."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        correspondence = getattr(obj, "correspondence", obj)
        if request.method in SAFE_METHODS:
            return can_view_correspondence_attachment(request.user, correspondence)
        if request.method == "DELETE":
            return can_delete_correspondence_attachment(request.user, obj)
        return can_upload_correspondence_attachment(request.user, correspondence)
