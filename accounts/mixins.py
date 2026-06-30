"""ViewSet mixins for project-scoped queryset filtering and write checks."""

from rest_framework.exceptions import PermissionDenied

from .rbac import (
    RBACDomain,
    extract_project_name_from_data,
    filter_queryset_by_project_access,
    project_from_instance,
    resolve_project,
    user_can_write_domain,
)


class ProjectRBACQuerysetMixin:
    """
    Filter list querysets to the user's assigned projects.

    Set on the ViewSet:
      rbac_project_field = 'project_name' | 'project' | 'project__name'
    """

    rbac_project_field = "project_name"

    def filter_queryset(self, queryset):
        qs = super().filter_queryset(queryset)
        user = getattr(self.request, "user", None)
        if user and user.is_authenticated:
            qs = filter_queryset_by_project_access(
                qs, user, project_name_field=self.rbac_project_field
            )
        return qs


class ProjectRBACWriteMixin:
    """Enforce write permission before create/update/destroy."""

    rbac_domain = RBACDomain.GENERAL

    def _rbac_project_for_write(self, serializer=None):
        if serializer and hasattr(serializer, "instance") and serializer.instance:
            return project_from_instance(serializer.instance)

        name = extract_project_name_from_data(getattr(self.request, "data", None))
        if name:
            return resolve_project(name)
        return None

    def perform_create(self, serializer):
        project = self._rbac_project_for_write(serializer)
        domain = getattr(self, "rbac_domain", RBACDomain.GENERAL)
        if project and not user_can_write_domain(self.request.user, project, domain):
            raise PermissionDenied(
                "You do not have permission to create this record for the project."
            )
        super().perform_create(serializer)

    def perform_update(self, serializer):
        project = self._rbac_project_for_write(serializer)
        domain = getattr(self, "rbac_domain", RBACDomain.GENERAL)
        if project and not user_can_write_domain(self.request.user, project, domain):
            raise PermissionDenied(
                "You do not have permission to update this record for the project."
            )
        super().perform_update(serializer)

    def perform_destroy(self, instance):
        project = project_from_instance(instance)
        domain = getattr(self, "rbac_domain", RBACDomain.GENERAL)
        if project and not user_can_write_domain(self.request.user, project, domain):
            raise PermissionDenied(
                "You do not have permission to delete this record for the project."
            )
        super().perform_destroy(instance)
