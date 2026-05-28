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


# =============================================================================
# HSE RECORD ADMIN
# =============================================================================

from .models import HSERecord


@admin.register(HSERecord)
class HSERecordAdmin(admin.ModelAdmin):
    """Admin interface for project-level HSE Records."""

    list_display = [
        "projectName",
        "fatalities",
        "significant",
        "major",
        "minor",
        "nearMiss",
        "totalManhours",
        "lossOfManhours",
        "created_at",
        "updated_at",
    ]
    list_filter = ["created_at"]
    search_fields = ["projectName"]
    ordering = ["projectName"]
    readonly_fields = ["created_at", "updated_at"]

    fieldsets = (
        ("Project", {"fields": ("projectName",)}),
        (
            "Incident Counts",
            {
                "fields": ("fatalities", "significant", "major", "minor", "nearMiss"),
            },
        ),
        (
            "Manhours",
            {
                "fields": ("totalManhours", "lossOfManhours"),
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )
