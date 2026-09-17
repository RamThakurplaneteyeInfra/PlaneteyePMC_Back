from django.contrib import admin
from .models import DailyProgressReport, DPRActivity


class DPRActivityInline(admin.TabularInline):
    """
    Inline admin for DPR Activities
    Allows editing activities directly within the DPR admin page
    """
    model = DPRActivity
    extra = 1
    fields = [
        'scope',
        'executed_quantity',
        'next_day_planned_work',
        'remarks'
    ]
    readonly_fields = [
        'cumulative_quantity',
        'remaining_quantity',
        'progress_percentage'
    ]


@admin.register(DailyProgressReport)
class DailyProgressReportAdmin(admin.ModelAdmin):
    """
    Admin interface for Daily Progress Report
    """
    list_display = [
        'id',
        'project_name',
        'job_no',
        'report_date',
        'issued_by',
        'designation',
        'created_at'
    ]
    list_filter = [
        'report_date',
        'created_at',
        'project_name'
    ]
    search_fields = [
        'project_name',
        'job_no',
        'issued_by',
        'designation'
    ]
    date_hierarchy = 'report_date'
    readonly_fields = ['created_at', 'updated_at']
    inlines = [DPRActivityInline]
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('project_name', 'job_no', 'report_date')
        }),
        ('Status Information', {
            'fields': (
                'unresolved_issues',
                'pending_letters',
                'quality_status',
                'next_day_incident',
                'bill_status',
                'gfc_status'
            )
        }),
        ('Issuer Information', {
            'fields': ('issued_by', 'designation')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(DPRActivity)
class DPRActivityAdmin(admin.ModelAdmin):
    """
    Admin interface for DPR Activity
    """
    list_display = [
        'id',
        'dpr',
        'scope',
        'executed_quantity',
        'cumulative_quantity',
        'progress_percentage',
        'remarks'
    ]
    list_filter = [
        'dpr__project_name',
        'dpr__report_date',
        'scope__category',
        'scope__subcategory'
    ]
    search_fields = [
        'remarks',
        'next_day_planned_work',
        'dpr__project_name',
        'scope__description'
    ]
    date_hierarchy = 'dpr__report_date'
    raw_id_fields = ['dpr', 'scope']
    readonly_fields = [
        'cumulative_quantity',
        'remaining_quantity',
        'progress_percentage'
    ]
