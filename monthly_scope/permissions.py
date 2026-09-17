from rest_framework import permissions
from django.contrib.auth.models import Group


class IsTeamLeader(permissions.BasePermission):
    """
    Custom permission to only allow Team Leaders to create/edit scopes
    """

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False

        # Check if user is in Team Leader group
        return request.user.groups.filter(name='Team Leader').exists()


class IsSiteEngineer(permissions.BasePermission):
    """
    Custom permission to only allow Site Engineers to view assigned scopes
    """

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False

        # Check if user is in any Site Engineer group
        site_engineer_groups = ['Site Engineer', 'Billing Site Engineer', 'QAQC Site Engineer']
        return request.user.groups.filter(name__in=site_engineer_groups).exists()


class IsTeamLeaderOrReadOnly(permissions.BasePermission):
    """
    Custom permission to allow Team Leaders full access, others read-only
    """

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return request.user.is_authenticated
        return request.user.groups.filter(name='Team Leader').exists()


class CanViewAssignedScopes(permissions.BasePermission):
    """
    Permission to view scopes assigned to the user's project
    """

    def has_object_permission(self, request, view, obj):
        if not request.user.is_authenticated:
            return False

        # Team Leaders can see all scopes
        if request.user.groups.filter(name='Team Leader').exists():
            return True

        # Site Engineers can only see scopes assigned to them
        if request.user.groups.filter(name__in=['Site Engineer', 'Billing Site Engineer', 'QAQC Site Engineer']).exists():
            return obj.assignments.filter(site_engineer=request.user).exists()

        return False


class CanManageScope(permissions.BasePermission):
    """
    Permission to manage (create/edit/delete) scopes
    Only Team Leaders can do this
    """

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False

        # Only Team Leaders can create/edit/delete scopes
        return request.user.groups.filter(name='Team Leader').exists()

    def has_object_permission(self, request, view, obj):
        if not request.user.is_authenticated:
            return False

        # Only Team Leaders can manage scopes
        return request.user.groups.filter(name='Team Leader').exists()


class CanViewScopes(permissions.BasePermission):
    """
    Permission to view scopes
    Team Leaders and Site Engineers can view scopes
    Only Team Leaders can modify
    """

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False

        # Allow read access for Team Leaders and Site Engineers
        if request.method in permissions.SAFE_METHODS:
            allowed_groups = ['Team Leader', 'Site Engineer', 'Billing Site Engineer', 'QAQC Site Engineer']
            return request.user.groups.filter(name__in=allowed_groups).exists()

        # Only Team Leaders can modify (POST, PUT, DELETE)
        return request.user.groups.filter(name='Team Leader').exists()

    def has_object_permission(self, request, view, obj):
        if not request.user.is_authenticated:
            return False

        # Team Leaders can do anything
        if request.user.groups.filter(name='Team Leader').exists():
            return True

        # Site Engineers can only see scopes assigned to them
        if request.method in permissions.SAFE_METHODS:
            site_engineer_groups = ['Site Engineer', 'Billing Site Engineer', 'QAQC Site Engineer']
            if request.user.groups.filter(name__in=site_engineer_groups).exists():
                return obj.assignments.filter(site_engineer=request.user).exists()

        return False