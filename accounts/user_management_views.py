"""
User Management API for Head Office (HO) and organizational Admins.

Endpoints under /api/users/:
  GET/POST          /
  GET/PATCH/DELETE  /{id}/
  PATCH             /{id}/change-password/
  PATCH             /{id}/reset-password/
  PATCH             /{id}/assign-projects/
  PATCH             /{id}/status/
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.models import UserManagementAuditLog
from accounts.permissions import CanManageUsers
from accounts.rbac import MANAGEABLE_PROJECT_ROLES, is_manageable_project_role
from accounts.user_management_serializers import (
    AssignProjectsSerializer,
    ManagedUserCreateSerializer,
    ManagedUserSerializer,
    ManagedUserUpdateSerializer,
    PasswordChangeSerializer,
    StatusUpdateSerializer,
)
from accounts.user_management_services import (
    assign_user_to_projects,
    create_managed_user,
    get_assigned_projects_for_user,
    get_assigned_projects_for_users,
    log_user_management_action,
    resolve_projects,
    set_managed_user_password,
    set_managed_user_status,
    update_managed_user,
)
from accounts.utils import get_user_role
from core.throttling import CreateRateThrottle, SearchRateThrottle, UpdateRateThrottle

User = get_user_model()


def _ok(message: str, data=None, http_status=status.HTTP_200_OK):
    body = {"success": True, "message": message}
    if data is not None:
        body["data"] = data
    return Response(body, status=http_status)


@method_decorator(never_cache, name="dispatch")
class ManagedUserViewSet(viewsets.ViewSet):
    """
    HO / Admin user management for Team Leaders and Engineers.
    """

    permission_classes = [CanManageUsers]
    throttle_classes = [SearchRateThrottle, CreateRateThrottle, UpdateRateThrottle]

    def _managed_queryset(self):
        """Only Team Leader / Engineer accounts appear in User Management."""
        return (
            User.objects.filter(groups__name__in=list(MANAGEABLE_PROJECT_ROLES))
            .distinct()
            .select_related("profile")
            .prefetch_related("groups")
            .order_by("username")
        )

    def _get_user(self, pk: str) -> User:
        user = self._managed_queryset().filter(pk=pk).first()
        if user is None:
            # Distinguish not-found vs privileged account
            raw = User.objects.filter(pk=pk).first()
            if raw is None:
                from rest_framework.exceptions import NotFound

                raise NotFound("The requested record could not be found.")
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied(
                "This account cannot be managed through User Management."
            )
        return user

    def list(self, request):
        qs = self._managed_queryset()

        search = (request.query_params.get("search") or "").strip()
        role = (request.query_params.get("role") or "").strip()
        project = (
            request.query_params.get("project")
            or request.query_params.get("project_id")
            or ""
        ).strip()
        status_filter = (
            request.query_params.get("status")
            or request.query_params.get("is_active")
            or ""
        ).strip().lower()

        if search:
            qs = qs.filter(
                Q(username__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(email__icontains=search)
                | Q(groups__name__icontains=search)
                | Q(lead_projects__name__icontains=search)
                | Q(primary_site_engineer_projects__name__icontains=search)
                | Q(billing_engineer_projects__name__icontains=search)
                | Q(qaqc_engineer_projects__name__icontains=search)
                | Q(hse_engineer_projects__name__icontains=search)
                | Q(assigned_projects__name__icontains=search)
                | Q(init_assigned_projects__name__icontains=search)
            ).distinct()

        if role:
            if role == "Team Lead":
                role = "Team Leader"
            qs = qs.filter(groups__name=role)

        if project:
            try:
                project_id = int(project)
                qs = qs.filter(
                    Q(lead_projects__id=project_id)
                    | Q(primary_site_engineer_projects__id=project_id)
                    | Q(billing_engineer_projects__id=project_id)
                    | Q(qaqc_engineer_projects__id=project_id)
                    | Q(hse_engineer_projects__id=project_id)
                    | Q(assigned_projects__id=project_id)
                    | Q(init_assigned_projects__id=project_id)
                ).distinct()
            except ValueError:
                qs = qs.filter(
                    Q(lead_projects__name__icontains=project)
                    | Q(primary_site_engineer_projects__name__icontains=project)
                    | Q(billing_engineer_projects__name__icontains=project)
                    | Q(qaqc_engineer_projects__name__icontains=project)
                    | Q(hse_engineer_projects__name__icontains=project)
                    | Q(assigned_projects__name__icontains=project)
                    | Q(init_assigned_projects__name__icontains=project)
                ).distinct()

        if status_filter in ("active", "true", "1"):
            qs = qs.filter(is_active=True)
        elif status_filter in ("inactive", "false", "0"):
            qs = qs.filter(is_active=False)

        # Pagination
        try:
            page = max(int(request.query_params.get("page", 1)), 1)
        except ValueError:
            page = 1
        try:
            page_size = min(max(int(request.query_params.get("page_size", 20)), 1), 100)
        except ValueError:
            page_size = 20

        total = qs.count()
        start = (page - 1) * page_size
        end = start + page_size
        items = list(qs[start:end])
        assigned_map = get_assigned_projects_for_users(items)
        data = ManagedUserSerializer(
            items,
            many=True,
            context={"assigned_projects_by_user": assigned_map},
        ).data

        return _ok(
            "Users retrieved successfully.",
            {
                "results": data,
                "count": total,
                "page": page,
                "page_size": page_size,
                "roles": sorted(MANAGEABLE_PROJECT_ROLES),
            },
        )

    def create(self, request):
        serializer = ManagedUserCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = create_managed_user(
            actor=request.user,
            username=data["username"],
            password=data["password"],
            confirm_password=data.get("confirm_password"),
            role=data["role"],
            project_ids=data["project_ids"],
            full_name=data.get("full_name"),
            email=data.get("email"),
            phone_number=data.get("phone_number"),
            is_active=data.get("is_active", True),
        )
        return _ok(
            "User created successfully.",
            ManagedUserSerializer(user).data,
            http_status=status.HTTP_201_CREATED,
        )

    def retrieve(self, request, pk=None):
        user = self._get_user(pk)
        return _ok("User retrieved successfully.", ManagedUserSerializer(user).data)

    def partial_update(self, request, pk=None):
        user = self._get_user(pk)
        serializer = ManagedUserUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = update_managed_user(
            actor=request.user,
            user=user,
            full_name=data.get("full_name"),
            username=data.get("username"),
            email=data.get("email"),
            phone_number=data.get("phone_number"),
            role=data.get("role"),
            project_ids=data.get("project_ids"),
            is_active=data.get("is_active"),
        )
        return _ok("User updated successfully.", ManagedUserSerializer(user).data)

    def destroy(self, request, pk=None):
        """Soft-delete: deactivate the user (keeps audit / assignment history)."""
        user = self._get_user(pk)
        user = set_managed_user_status(actor=request.user, user=user, is_active=False)
        log_user_management_action(
            performed_by=request.user,
            target_user=user,
            action=UserManagementAuditLog.ACTION_DELETED,
            detail="User soft-deleted (deactivated).",
            projects=get_assigned_projects_for_user(user),
        )
        return _ok(
            "User deactivated successfully.",
            ManagedUserSerializer(user).data,
        )

    @action(detail=True, methods=["patch"], url_path="change-password")
    def change_password(self, request, pk=None):
        user = self._get_user(pk)
        serializer = PasswordChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        set_managed_user_password(
            actor=request.user,
            user=user,
            password=data["password"],
            confirm_password=data.get("confirm_password"),
            action=UserManagementAuditLog.ACTION_PASSWORD_CHANGED,
        )
        return _ok("Password changed successfully.")

    @action(detail=True, methods=["patch"], url_path="reset-password")
    def reset_password(self, request, pk=None):
        user = self._get_user(pk)
        serializer = PasswordChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        set_managed_user_password(
            actor=request.user,
            user=user,
            password=data["password"],
            confirm_password=data.get("confirm_password"),
            action=UserManagementAuditLog.ACTION_PASSWORD_RESET,
        )
        return _ok("Password reset successfully.")

    @action(detail=True, methods=["patch"], url_path="assign-projects")
    def assign_projects(self, request, pk=None):
        user = self._get_user(pk)
        serializer = AssignProjectsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        projects = resolve_projects(serializer.validated_data["project_ids"])
        if not projects:
            from rest_framework.exceptions import ValidationError

            raise ValidationError(
                {"project_ids": "Please select at least one project."}
            )
        role = get_user_role(user)
        if not is_manageable_project_role(role):
            from rest_framework.exceptions import ValidationError

            raise ValidationError(
                {"role": "This user does not have an assignable project role."}
            )
        assign_user_to_projects(user, projects, role=role)
        log_user_management_action(
            performed_by=request.user,
            target_user=user,
            action=UserManagementAuditLog.ACTION_PROJECTS_ASSIGNED,
            detail=f"Assigned to {len(projects)} project(s).",
            projects=projects,
        )
        user = self._get_user(pk)
        return _ok(
            "Project assignments updated successfully.",
            ManagedUserSerializer(user).data,
        )

    @action(detail=True, methods=["patch"], url_path="status")
    def update_status(self, request, pk=None):
        user = self._get_user(pk)
        serializer = StatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = set_managed_user_status(
            actor=request.user,
            user=user,
            is_active=serializer.validated_data["is_active"],
        )
        state = "activated" if user.is_active else "deactivated"
        return _ok(f"User {state} successfully.", ManagedUserSerializer(user).data)
