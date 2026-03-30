from django.contrib import admin
from .models import Project, Site

@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'client_name', 'status', 'commencement_date', 'budget', 'revised_contract_value', 'delay_days')
    list_filter = ('status', 'has_documentation')
    search_fields = ('name', 'client_name', 'description')
    readonly_fields = ('revised_contract_value', 'delay_days', 'created_at')
    
    fieldsets = (
        ("Basic Information", {
            'fields': ('name', 'client_name', 'description', 'location', 'status')
        }),
        ("Timeline & Budget", {
            'fields': ('commencement_date', 'duration', 'budget')
        }),
        ("Project Details", {
            'fields': ('salient_features', 'site_staff_details')
        }),
        ("Compliance & Documentation", {
            'fields': ('has_documentation', 'documentation_file', 'has_iso_checklist', 'has_test_frequency_chart')
        }),
        # ==========================================================================
        # Project Initialization Fields (PMC Head Input)
        # ==========================================================================
        ("Project Initialization", {
            'classes': ('collapse',),
            'fields': (
                # Project Dates
                ('project_start', 'contract_finish', 'forecast_finish'),
                # Contract Values
                ('original_contract_value', 'approved_vo', 'pending_vo', 'revised_contract_value'),
                # Budget
                ('bac',),
                # Work Configuration
                ('working_hours_per_day', 'working_days_per_month'),
                # Calculated Fields (read-only)
                ('delay_days', 'created_at'),
            )
        }),
    )

@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ('name', 'project', 'location', 'status')
    list_filter = ('status', 'project')
    search_fields = ('name', 'location')
