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

from .models import HSERecord, HealthSafetyRecord


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


@admin.register(HealthSafetyRecord)
class HealthSafetyRecordAdmin(admin.ModelAdmin):
    """Admin interface for monthly Health & Safety records."""

    list_display = [
        "project_name",
        "month",
        "year",
        "average_daily_manpower",
        "working_days",
        "man_hours_worked",
        "near_miss",
        "reportable_accident_lti",
        "medical_checkup_total",
        "created_at",
    ]
    list_filter = ["year", "month", "project_name"]
    search_fields = ["project_name"]
    ordering = ["project_name", "year", "month"]
    readonly_fields = [
        "man_days_worked",
        "man_hours_worked",
        "medical_checkup_total",
        "created_at",
        "updated_at",
    ]

    fieldsets = (
        ("Project & Period", {"fields": ("project_name", "month", "year")}),
        (
            "Monthly Manpower",
            {
                "fields": (
                    "average_daily_manpower",
                    "working_days",
                    "man_days_worked",
                    "man_hours_worked",
                    "total_manhours",
                    "loss_of_manhours",
                )
            },
        ),
        (
            "Incidents & Cases",
            {
                "fields": (
                    "fatalities",
                    "significant",
                    "major",
                    "minor",
                    "near_miss",
                    "reportable_accident_lti",
                    "dangerous_occurrences",
                    "first_aid_cases",
                    "medical_treatment_cases",
                    "utility_damage",
                )
            },
        ),
        (
            "Training & Drills",
            {
                "fields": (
                    "internal_training_count",
                    "internal_training_hours",
                    "external_training_count",
                    "external_training_hours",
                    "mock_drills",
                )
            },
        ),
        (
            "Medical Checkups",
            {
                "fields": (
                    "medical_checkup_workers",
                    "medical_checkup_staff",
                    "medical_checkup_total",
                )
            },
        ),
        (
            "Timestamps",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )
