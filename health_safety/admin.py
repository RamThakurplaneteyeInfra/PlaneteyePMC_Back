# Health & Safety Admin Configuration
from django.contrib import admin
from .models import HealthSafetyReport


@admin.register(HealthSafetyReport)
class HealthSafetyReportAdmin(admin.ModelAdmin):
    """Admin interface for Health & Safety Reports"""
    list_display = [
        'project_name', 'report_date', 'total_manhours',
        'fatalities', 'significant', 'major', 'minor', 'near_miss',
        'created_at'
    ]
    list_filter = ['report_date', 'project_name']
    search_fields = ['project_name']
    ordering = ['-report_date', '-created_at']
    date_hierarchy = 'report_date'
    
    fieldsets = (
        ('Project Information', {
            'fields': ('project_name', 'report_date')
        }),
        ('Manhours', {
            'fields': ('total_manhours',)
        }),
        ('Incident Counts', {
            'fields': ('fatalities', 'significant', 'major', 'minor', 'near_miss'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    readonly_fields = ['created_at', 'updated_at']
