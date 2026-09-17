from django import forms
from django.contrib import admin
from django.contrib.auth.models import User

from .models import Project, Site


def _users_in_groups(*group_names):
    return (
        User.objects.filter(groups__name__in=group_names, is_active=True)
        .distinct()
        .order_by("username")
    )


class ProjectAdminForm(forms.ModelForm):
    """Limit assignment dropdowns to users with the matching PMC role."""

    class Meta:
        model = Project
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        role_fields = {
            "pmc_head": ("PMC Head", "CEO", "Head Office", "HO"),
            "team_lead": ("Team Leader", "Team Lead"),
            "site_engineer": ("Site Engineer",),
            "billing_site_engineer": ("Billing Site Engineer",),
            "qaqc_site_engineer": ("QAQC Site Engineer",),
            "hse_site_engineer": ("HSE Site Engineer",),
        }
        for field_name, groups in role_fields.items():
            if field_name in self.fields:
                qs = _users_in_groups(*groups)
                # Keep currently assigned user visible even if inactive / no group
                current = getattr(self.instance, f"{field_name}_id", None) if self.instance else None
                if current:
                    qs = (qs | User.objects.filter(pk=current)).distinct().order_by("username")
                self.fields[field_name].queryset = qs
                self.fields[field_name].help_text = (
                    f"Users in group(s): {', '.join(groups)}. "
                    "Create users under Authentication → Users and assign the group first."
                )

        if "site_engineers" in self.fields:
            qs = _users_in_groups(
                "Site Engineer",
                "Billing Site Engineer",
                "QAQC Site Engineer",
                "HSE Site Engineer",
            )
            if self.instance and self.instance.pk:
                qs = (qs | self.instance.site_engineers.all()).distinct().order_by("username")
            self.fields["site_engineers"].queryset = qs

        if "coordinators" in self.fields:
            qs = _users_in_groups("PMC Manager", "Coordinator")
            if self.instance and self.instance.pk:
                qs = (qs | self.instance.coordinators.all()).distinct().order_by("username")
            self.fields["coordinators"].queryset = qs


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    form = ProjectAdminForm
    list_display = (
        "name",
        "client_name",
        "status",
        "team_lead",
        "site_engineer",
        "billing_site_engineer",
        "qaqc_site_engineer",
        "hse_site_engineer",
        "commencement_date",
        "budget",
    )
    list_filter = ("status", "has_documentation")
    search_fields = ("name", "client_name", "description")
    readonly_fields = ("revised_contract_value", "delay_days", "created_at", "updated_at")
    autocomplete_fields = ()
    filter_horizontal = ("site_engineers", "coordinators")
    raw_id_fields = ()
    list_select_related = (
        "team_lead",
        "site_engineer",
        "billing_site_engineer",
        "qaqc_site_engineer",
        "hse_site_engineer",
    )

    fieldsets = (
        (
            "Basic Information",
            {"fields": ("name", "client_name", "description", "location", "status")},
        ),
        (
            "Team Assignment",
            {
                "description": (
                    "Assign Team Leader and Site Engineers created under "
                    "Authentication → Users (with the matching Group / role). "
                    "Primary Site Engineer is also added to the Site Engineers list on save."
                ),
                "fields": (
                    "pmc_head",
                    "team_lead",
                    "site_engineer",
                    "billing_site_engineer",
                    "qaqc_site_engineer",
                    "hse_site_engineer",
                    "site_engineers",
                    "coordinators",
                ),
            },
        ),
        (
            "Timeline & Budget",
            {"fields": ("commencement_date", "duration", "budget", "start_date", "end_date")},
        ),
        (
            "Project Details",
            {"fields": ("salient_features", "site_staff_details")},
        ),
        (
            "Compliance & Documentation",
            {
                "fields": (
                    "has_documentation",
                    "documentation_file",
                    "has_iso_checklist",
                    "has_test_frequency_chart",
                )
            },
        ),
        (
            "Project Initialization",
            {
                "classes": ("collapse",),
                "fields": (
                    ("project_start", "contract_finish", "forecast_finish"),
                    (
                        "original_contract_value",
                        "approved_vo",
                        "pending_vo",
                        "revised_contract_value",
                    ),
                    ("bac",),
                    ("working_hours_per_day", "working_days_per_month"),
                    ("delay_days", "created_at", "updated_at"),
                ),
            },
        ),
    )

    def save_model(self, request, obj, form, change):
        if not change and request.user.is_authenticated and not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
        # Keep M2M in sync with primary site engineer FK
        if obj.site_engineer_id:
            obj.site_engineers.add(obj.site_engineer)


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ("name", "project", "location", "status")
    list_filter = ("status", "project")
    search_fields = ("name", "location")
    autocomplete_fields = ("project",)
