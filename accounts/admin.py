from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from .models import UserProfile

# We "Unregister" the old user admin and "Register" a new one
try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass


class UserProfileInline(admin.StackedInline):
    """Inline admin for UserProfile"""
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'Profile'
    fields = ('site_engineer_type', 'phone_number', 'designation', 'department')


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    """Custom User Admin with profile inline"""
    inlines = (UserProfileInline,)
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff', 'get_groups', 'get_primary_role')

    def get_groups(self, obj):
        return ", ".join([group.name for group in obj.groups.all()])
    get_groups.short_description = 'Groups (Roles)'

    def get_primary_role(self, obj):
        """Get primary role from profile or groups"""
        try:
            return obj.profile.get_primary_role() or "No Role"
        except UserProfile.DoesNotExist:
            groups = obj.groups.all()
            if groups.exists():
                return groups.first().name
            return "No Role"
    get_primary_role.short_description = 'Primary Role'


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    """Admin for UserProfile"""
    list_display = ('user', 'get_primary_role', 'site_engineer_type', 'designation', 'department')
    list_filter = ('site_engineer_type', 'department')
    search_fields = ('user__username', 'user__email', 'user__first_name', 'user__last_name', 'designation')
    
    def get_primary_role(self, obj):
        return obj.get_primary_role()
    get_primary_role.short_description = 'Primary Role'
