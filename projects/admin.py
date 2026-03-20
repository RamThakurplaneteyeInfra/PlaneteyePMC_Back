from django.contrib import admin
from .models import Project, Site

@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'client_name', 'status', 'commencement_date', 'budget')
    list_filter = ('status', 'has_documentation')
    search_fields = ('name', 'client_name', 'description')
    
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
    )

@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ('name', 'project', 'location', 'status')
    list_filter = ('status', 'project')
    search_fields = ('name', 'location')
