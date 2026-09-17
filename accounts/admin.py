from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.contrib.auth.models import Group, User
from django.utils.translation import gettext_lazy as _

from .models import UserManagementAuditLog, UserProfile

try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass


# Role groups used across PMC (shown prominently in User admin help text)
PMC_ROLE_GROUPS = (
    "CEO",
    "Head Office",
    "PMC Head",
    "PMC Manager",
    "Team Leader",
    "Site Engineer",
    "Billing Site Engineer",
    "QAQC Site Engineer",
    "HSE Site Engineer",
)


class PMCUserCreationForm(UserCreationForm):
    """User creation form that also allows assigning PMC role groups."""

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "groups")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "groups" in self.fields:
            self.fields["groups"].required = False
            self.fields["groups"].help_text = (
                "Select the PMC role (Team Leader, Site Engineer, etc.)."
            )


class PMCUserChangeForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = User


class UserProfileInline(admin.StackedInline):
    """Inline admin for UserProfile (one profile per user)."""

    model = UserProfile
    can_delete = False
    max_num = 1
    extra = 0
    fk_name = "user"
    verbose_name_plural = "Profile"
    fields = ("site_engineer_type", "phone_number", "designation", "department")

    def get_extra(self, request, obj=None, **kwargs):
        # On add: show one empty profile form. On change: only if missing.
        if obj is None:
            return 1
        if hasattr(obj, "profile"):
            return 0
        return 1


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    """
    Custom User Admin with profile inline and clearer PMC role guidance.

    Create Team Leaders / Site Engineers here:
      1. Add user + password + role group
      2. For site engineers, set Profile → site engineer type
      3. Assign the user on a Project under Projects → Team Assignment
    """

    add_form = PMCUserCreationForm
    form = PMCUserChangeForm
    inlines = (UserProfileInline,)
    list_display = (
        "username",
        "email",
        "first_name",
        "last_name",
        "is_active",
        "is_staff",
        "get_groups",
        "get_primary_role",
    )
    list_filter = ("is_active", "is_staff", "groups")
    search_fields = ("username", "email", "first_name", "last_name")
    filter_horizontal = ("groups", "user_permissions")

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        (_("Personal info"), {"fields": ("first_name", "last_name", "email")}),
        (
            _("PMC Roles (Groups)"),
            {
                "fields": ("groups",),
                "description": (
                    "Assign exactly one primary PMC role group: "
                    + ", ".join(PMC_ROLE_GROUPS)
                    + ". "
                    "For Site Engineer roles also set Profile → Site engineer type. "
                    "Then assign this user to a project under Projects → Team Assignment."
                ),
            },
        ),
        (
            _("Permissions"),
            {
                "fields": ("is_active", "is_staff", "is_superuser", "user_permissions"),
            },
        ),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "password1", "password2", "groups"),
                "description": (
                    "Create the user, assign a PMC role group "
                    "(Team Leader, Site Engineer, Billing/QAQC/HSE Site Engineer), "
                    "then set Profile fields below. "
                    "Finally assign them on a Project under Team Assignment."
                ),
            },
        ),
    )

    def get_inline_instances(self, request, obj=None):
        # Always show Profile inline on add and change (needed for site engineer type).
        return super(UserAdmin, self).get_inline_instances(request, obj)

    def get_groups(self, obj):
        return ", ".join(group.name for group in obj.groups.all()) or "—"

    get_groups.short_description = "Groups (Roles)"

    def get_primary_role(self, obj):
        try:
            return obj.profile.get_primary_role() or "No Role"
        except UserProfile.DoesNotExist:
            groups = obj.groups.all()
            if groups.exists():
                return groups.first().name
            return "No Role"

    get_primary_role.short_description = "Primary Role"

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # Guarantee profile exists before inline formset saves (avoids 500).
        UserProfile.objects.get_or_create(user=obj)

    def save_formset(self, request, form, formset, change):
        """
        Merge profile inline into the single OneToOne profile.

        Avoids IntegrityError when the post_save signal already created a
        UserProfile and the admin inline would otherwise INSERT a second row.
        """
        if formset.model is UserProfile:
            profile, _ = UserProfile.objects.get_or_create(user=form.instance)
            applied = False
            for inline_form in formset.forms:
                data = getattr(inline_form, "cleaned_data", None) or {}
                if not data or data.get("DELETE"):
                    continue
                for field in (
                    "site_engineer_type",
                    "phone_number",
                    "designation",
                    "department",
                ):
                    if field in data:
                        setattr(profile, field, data[field])
                profile.user = form.instance
                profile.save()
                applied = True
            formset.new_objects = []
            formset.changed_objects = [(profile, [])] if applied else []
            formset.deleted_objects = []
            return
        super().save_formset(request, form, formset, change)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    """Admin for UserProfile."""

    list_display = (
        "user",
        "get_primary_role",
        "site_engineer_type",
        "designation",
        "department",
    )
    list_filter = ("site_engineer_type", "department")
    search_fields = (
        "user__username",
        "user__email",
        "user__first_name",
        "user__last_name",
        "designation",
    )
    autocomplete_fields = ("user",)
    raw_id_fields = ("user",)

    def get_primary_role(self, obj):
        return obj.get_primary_role()

    get_primary_role.short_description = "Primary Role"


@admin.register(UserManagementAuditLog)
class UserManagementAuditLogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "action",
        "performed_by",
        "target_username",
        "target_role",
        "project",
    )
    list_filter = ("action", "created_at")
    search_fields = (
        "target_username",
        "target_role",
        "detail",
        "project_names",
        "performed_by__username",
    )
    readonly_fields = (
        "performed_by",
        "target_user",
        "target_username",
        "target_role",
        "project",
        "project_names",
        "action",
        "detail",
        "created_at",
    )
    ordering = ("-created_at",)


# Ensure role groups exist so admins can assign them from the Groups picker
@admin.action(description="Ensure standard PMC role groups exist")
def ensure_pmc_role_groups(modeladmin, request, queryset):
    created = []
    for name in PMC_ROLE_GROUPS:
        _, was_created = Group.objects.get_or_create(name=name)
        if was_created:
            created.append(name)
    if created:
        modeladmin.message_user(request, f"Created groups: {', '.join(created)}")
    else:
        modeladmin.message_user(request, "All PMC role groups already exist.")


try:
    from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin

    class GroupAdmin(BaseGroupAdmin):
        actions = list(getattr(BaseGroupAdmin, "actions", []) or []) + [
            ensure_pmc_role_groups
        ]

    try:
        admin.site.unregister(Group)
    except admin.sites.NotRegistered:
        pass
    admin.site.register(Group, GroupAdmin)
except Exception:
    pass
